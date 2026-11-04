#!/usr/bin/env python3
"""Opt-in, loopback-only HTTP transport for the Debian 13 read-only MCP tools.

This exposes the existing 2025-11-25 JSON-RPC MCP server over stateless
Streamable HTTP. It is NOT a publicly reachable HTTPS service or an OAuth
provider. Use an authenticated, reviewed TLS reverse proxy / private tunnel
before connecting an external client.
"""
from __future__ import annotations

import hmac
import http.server
import json
import os
import urllib.parse

import mcp_server

MAX_REQUEST_BYTES = 65536
ALLOWED_METHODS = frozenset({
    "initialize", "ping", "tools/list", "tools/call", "notifications/initialized",
})


def validate_token(token: str) -> None:
    if (not isinstance(token, str) or len(token) < 32
            or not token.isascii() or any(not 33 <= ord(c) <= 126 for c in token)):
        raise ValueError("Set a strong printable DEBIAN13_MCP_GATEWAY_TOKEN (32+ characters).")


def allowed_origins_from_env(value: str) -> frozenset[str]:
    origins = set()
    for entry in value.split(","):
        origin = entry.strip()
        if not origin:
            continue
        parsed = urllib.parse.urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment
                or parsed.netloc.lower() != parsed.netloc or origin.endswith("/")):
            raise ValueError("Allowed MCP origins must be exact HTTPS origins without paths.")
        origins.add(origin)
    return frozenset(origins)


class MCPHTTPGateway(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], token: str,
                 allowed_origins: frozenset[str] = frozenset()):
        # Never bind to a public interface, even when supplied an unsafe CLI value.
        if address[0] != "127.0.0.1":
            raise ValueError("MCP gateway must bind only to 127.0.0.1.")
        validate_token(token)
        self.gateway_token = token
        self.allowed_origins = allowed_origins
        super().__init__(address, MCPHandler)


class MCPHandler(http.server.BaseHTTPRequestHandler):
    server: MCPHTTPGateway
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        # Never log authorization headers, request bodies or query strings.
        return

    def _reply(self, status: int, body: dict | None = None, *, allow: str = "") -> None:
        encoded = (json.dumps(body, ensure_ascii=False).encode("utf-8")
                   if body is not None else b"")
        self.send_response(status)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if body is not None:
            self.send_header("Content-Type", "application/json")
        if allow:
            self.send_header("Allow", allow)
        self.send_header("Connection", "close")
        self.end_headers()
        if encoded:
            self.wfile.write(encoded)
        self.close_connection = True

    def _guard(self) -> bool:
        expected_hosts = {"127.0.0.1:" + str(self.server.server_port),
                          "localhost:" + str(self.server.server_port)}
        if self.headers.get("Host", "") not in expected_hosts:
            self._reply(403, {"error": "Invalid Host"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.server.allowed_origins:
            self._reply(403, {"error": "Untrusted Origin"})
            return False
        expected = "Bearer " + self.server.gateway_token
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
            self._reply(401, {"error": "Authentication required"})
            return False
        return True

    def do_GET(self) -> None:
        if self.path != "/mcp":
            self._reply(404, {"error": "Not found"})
        elif self._guard():
            # Stateless MCP; no standalone server-to-client SSE stream.
            self._reply(405, {"error": "GET SSE not supported"}, allow="POST")

    def do_DELETE(self) -> None:
        if self.path != "/mcp":
            self._reply(404, {"error": "Not found"})
        elif self._guard():
            self._reply(405, {"error": "Stateless server has no sessions"}, allow="POST")

    def do_POST(self) -> None:
        if self.path != "/mcp":
            self._reply(404, {"error": "Not found"})
            return
        if not self._guard():
            return
        if self.headers.get("Transfer-Encoding"):
            self._reply(400, {"error": "Chunked request bodies are unsupported"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
            self._reply(415, {"error": "Content-Type must be application/json"})
            return
        accepted = self.headers.get("Accept", "").lower()
        if "application/json" not in accepted or "text/event-stream" not in accepted:
            self._reply(406, {"error": "Accept must include JSON and event-stream"})
            return
        version = self.headers.get("MCP-Protocol-Version")
        if version is not None and version != mcp_server.PROTOCOL_VERSION:
            self._reply(400, {"error": "Unsupported MCP protocol version"})
            return
        length = self.headers.get("Content-Length", "")
        if not length.isdecimal() or len(length) > 8:
            self._reply(411, {"error": "Content-Length required"})
            return
        count = int(length)
        if not 0 < count <= MAX_REQUEST_BYTES:
            self._reply(413, {"error": "Request size outside limit"})
            return
        try:
            raw = self.rfile.read(count)
            if len(raw) != count:
                raise ValueError
            req = json.loads(raw)
        except (ValueError, UnicodeError):
            self._reply(400, {"error": "Invalid JSON request"})
            return
        if (not isinstance(req, dict) or req.get("jsonrpc") != "2.0"
                or req.get("method") not in ALLOWED_METHODS):
            self._reply(400, {"error": "Invalid MCP request method"})
            return
        if req["method"] == "notifications/initialized" and "id" in req:
            self._reply(400, {"error": "Notification must not have an id"})
            return
        if req["method"] != "notifications/initialized" and "id" not in req:
            self._reply(400, {"error": "JSON-RPC request id required"})
            return
        reply = mcp_server.response(req)
        if reply is None:
            self._reply(202)
        else:
            self._reply(200, reply)


def main() -> None:
    token = os.environ.get("DEBIAN13_MCP_GATEWAY_TOKEN", "")
    validate_token(token)
    backend_token = os.environ.get("DEBIAN13_API_TOKEN", "")
    validate_token(backend_token)
    if hmac.compare_digest(token, backend_token):
        raise ValueError("Gateway and backend API tokens must be different.")
    origins = allowed_origins_from_env(
        os.environ.get("DEBIAN13_MCP_ALLOWED_ORIGINS", ""))
    port = int(os.environ.get("DEBIAN13_MCP_GATEWAY_PORT", "8766"))
    if not 1024 <= port <= 65535:
        raise ValueError("Gateway port must be between 1024 and 65535.")
    with MCPHTTPGateway(("127.0.0.1", port), token, origins) as gateway:
        print("Debian 13 MCP: local read-only HTTP ready (HTTPS/OAuth NOT configured)",
              flush=True)
        gateway.serve_forever(poll_interval=0.3)


if __name__ == "__main__":
    main()
