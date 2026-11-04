#!/usr/bin/env python3
"""Safe local end-to-end MCP check; never asserts ChatGPT or agents are connected.

Checks a running loopback Debian 13 MCP gateway against the real authenticated
backend, using only read-only tools. No model inference or paid API requests.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

MCP_PROTOCOL = "2025-11-25"
EXPECTED_TOOLS = frozenset({
    "debian13_profiles", "debian13_diagnostics", "debian13_integrations",
    "debian13_work_tasks", "debian13_original_agents",
    "alex_existing_status", "alex_existing_tasks",
})
MAX_RESULT = 256 * 1024


class ProbeError(Exception):
    """Safe-to-display error that never includes URL, token or response body."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(port: int, token: str, request: dict) -> dict:
    raw = json.dumps(request, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp",
        data=raw,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL,
        },
        method="POST",
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=4) as res:
            if res.status != 200 or not res.headers.get("Content-Type", "").startswith("application/json"):
                raise ProbeError("MCP returned an unexpected HTTP status or content type.")
            raw_response = res.read(MAX_RESULT + 1)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ProbeError("MCP loopback request failed; verify gateway, token and backend.") from None
    if len(raw_response) > MAX_RESULT:
        raise ProbeError("MCP response exceeded the configured size limit.")
    try:
        payload = json.loads(raw_response)
    except (ValueError, UnicodeError):
        raise ProbeError("MCP returned invalid JSON.") from None
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise ProbeError("MCP returned an invalid JSON-RPC envelope.")
    if payload.get("id") != request["id"] or "error" in payload or not isinstance(payload.get("result"), dict):
        raise ProbeError("MCP JSON-RPC request was rejected.")
    return payload["result"]


def _call(port: int, token: str, tool: str, request_id: int) -> dict:
    result = _request(port, token, {
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": tool, "arguments": {}},
    })
    if result.get("isError") is not False:
        raise ProbeError("A Debian 13 backend tool reported unavailable or invalid data.")
    try:
        value = json.loads(result["content"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise ProbeError("MCP tool returned a malformed result.") from None
    if not isinstance(value, dict):
        raise ProbeError("MCP tool did not return an object.")
    return value


def check_local(port: int, token: str) -> dict:
    # Explicit loopback destination only. The token is never logged or printed.
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ProbeError("Invalid local gateway port.")
    if (not isinstance(token, str) or len(token) < 32 or not token.isascii()
            or any(not 33 <= ord(c) <= 126 for c in token)):
        raise ProbeError("A valid private MCP gateway token is required.")
    initialized = _request(port, token, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": MCP_PROTOCOL, "capabilities": {},
                   "clientInfo": {"name": "debian13-local-preflight", "version": "1"}},
    })
    if initialized.get("protocolVersion") != MCP_PROTOCOL:
        raise ProbeError("MCP protocol negotiation did not match.")

    listed = _request(port, token, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = listed.get("tools")
    if not isinstance(tools, list):
        raise ProbeError("MCP tool list is missing.")
    names = {t.get("name") for t in tools if isinstance(t, dict)
             and isinstance(t.get("name"), str)}
    if names != EXPECTED_TOOLS:
        raise ProbeError("Unexpected MCP tool inventory; review changes before connecting.")
    if not all(isinstance(t, dict) and isinstance(t.get("annotations"), dict)
               and t["annotations"].get("readOnlyHint") is True
               and t["annotations"].get("destructiveHint") is False
               for t in tools):
        raise ProbeError("Non-read-only MCP tool advertised; remote access blocked.")

    integrations = _call(port, token, "debian13_integrations", 3)
    originals = _call(port, token, "debian13_original_agents", 4)
    tasks = _call(port, token, "debian13_work_tasks", 5)
    diagnostics = _call(port, token, "debian13_diagnostics", 6)

    if not isinstance(integrations.get("integrations"), list):
        raise ProbeError("Backend integration status was not available.")
    if (not isinstance(originals.get("agents"), list)
            or len(originals["agents"]) != 4
            or not isinstance(originals.get("originalAgentExecutionVerified"), bool)):
        raise ProbeError("Original agent status has an unexpected format.")
    if (not isinstance(tasks.get("tasks"), list)
            or not isinstance(tasks.get("workersRunning"), int)
            or tasks.get("workersRunning") < 0
            or tasks.get("storage") != "sqlite"):
        raise ProbeError("Work queue status has an unexpected format.")
    if diagnostics.get("service") != "debian13-system":
        raise ProbeError("Unexpected backend service identity.")

    return {
        "localMcpStatus": "verified",
        "transport": "loopback_http",
        "protocolVersion": MCP_PROTOCOL,
        "authentication": "verified",
        "readOnlyToolCount": len(names),
        "backend": "reachable",
        "workQueueCount": len(tasks["tasks"]),
        "workersReportedByBackend": tasks["workersRunning"],
        "originalAgentRegistryReachable": originals.get("registryReachable") is True,
        "originalAgentExecutionVerified": originals["originalAgentExecutionVerified"],
        "originalAgentWorkersVerified": sum(
            a.get("workerVerified") is True for a in originals["agents"]
            if isinstance(a, dict)),
        "integrations": {
            item["id"]: item.get("connected") is True
            for item in integrations["integrations"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        },
        "chatgptExternalConnection": "not_tested",
        "publicMcpEndpoint": "not_deployed_by_this_check",
    }


def _private_token() -> str:
    token = os.environ.get("DEBIAN13_MCP_GATEWAY_TOKEN", "")
    if token:
        return token
    state = os.environ.get("DEBIAN13_STATE_DIR")
    if not state:
        state = str(Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
                    / "debian13")
    file = Path(state) / "mcp-gateway-token"
    try:
        if file.is_symlink() or file.stat().st_mode & 0o077:
            raise ProbeError("Gateway token file permissions are not private.")
        return file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise ProbeError("Private MCP token unavailable; start local MCP first.") from None


def main() -> int:
    try:
        port = int(os.environ.get("DEBIAN13_MCP_GATEWAY_PORT", "8766"))
        result = check_local(port, _private_token())
    except (ValueError, ProbeError) as exc:
        reason = str(exc) if isinstance(exc, ProbeError) else "Invalid MCP gateway port."
        print("BLOCKED: " + reason, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
