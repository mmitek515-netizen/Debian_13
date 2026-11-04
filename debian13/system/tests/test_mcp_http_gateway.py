"""Live loopback HTTP checks for Debian 13's opt-in read-only MCP gateway."""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

SYSTEM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM))

from server import Debian13Server
from mcp_http_gateway import (
    MCPHTTPGateway, allowed_origins_from_env, validate_token,
)
import mcp_server

BACKEND_TOKEN = "debian13-test-backend-secret-32-characters"
GATEWAY_TOKEN = "debian13-test-gateway-secret-32-characters"
ACCEPT = "application/json, text/event-stream"


class MCPHTTPGatewayTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.backend = Debian13Server(("127.0.0.1", 0), {
            "api_token": BACKEND_TOKEN, "model_chat_url": "", "model_api_key": "",
            "model_name": "", "workspace": self.workspace.name,
        })
        self.environment = patch.dict(os.environ, {
            "DEBIAN13_API_TOKEN": BACKEND_TOKEN,
            "DEBIAN13_SYSTEM_API_URL": (
                "http://127.0.0.1:" + str(self.backend.server_port)),
        })
        self.environment.start()
        self.gateway = MCPHTTPGateway(("127.0.0.1", 0), GATEWAY_TOKEN,
                                      frozenset({"https://chatgpt.com"}))
        self.backend_thread = threading.Thread(
            target=self.backend.serve_forever, daemon=True)
        self.gateway_thread = threading.Thread(
            target=self.gateway.serve_forever, daemon=True)
        self.backend_thread.start()
        self.gateway_thread.start()

    def tearDown(self):
        self.gateway.shutdown()
        self.backend.shutdown()
        self.gateway.server_close()
        self.backend.server_close()
        self.gateway_thread.join(timeout=3)
        self.backend_thread.join(timeout=3)
        self.environment.stop()
        self.workspace.cleanup()

    def request(self, request=None, method="POST", path="/mcp", extras=None):
        payload = None if request is None else json.dumps(request).encode("utf-8")
        headers = {
            "Host": "127.0.0.1:" + str(self.gateway.server_port),
            "Content-Type": "application/json",
            "Accept": ACCEPT,
            "Authorization": "Bearer " + GATEWAY_TOKEN,
            "MCP-Protocol-Version": mcp_server.PROTOCOL_VERSION,
        }
        if extras:
            headers.update(extras)
        conn = http.client.HTTPConnection(
            "127.0.0.1", self.gateway.server_port, timeout=4)
        try:
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            result = json.loads(raw) if raw else None
            return resp.status, result, dict(resp.getheaders())
        finally:
            conn.close()

    def test_initialize_list_tools_and_real_read_only_backend_calls(self):
        status, initialized, _ = self.request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": mcp_server.PROTOCOL_VERSION},
        })
        self.assertEqual(status, 200)
        self.assertEqual(initialized["result"]["protocolVersion"],
                         mcp_server.PROTOCOL_VERSION)

        status, notification, _ = self.request({
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        self.assertEqual(status, 202)
        self.assertIsNone(notification)

        status, listed, _ = self.request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list",
        })
        self.assertEqual(status, 200)
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertIn("debian13_original_agents", names)
        self.assertIn("debian13_work_tasks", names)
        self.assertTrue(all(tool["annotations"]["readOnlyHint"]
                            for tool in listed["result"]["tools"]))

        for name in ("debian13_original_agents", "debian13_work_tasks"):
            status, result, _ = self.request({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            })
            self.assertEqual(status, 200)
            self.assertFalse(result["result"]["isError"])
            data = json.loads(result["result"]["content"][0]["text"])
            if name == "debian13_work_tasks":
                self.assertEqual(data["workersRunning"], 0)
                self.assertEqual(data["tasks"], [])
            else:
                self.assertFalse(data["originalAgentExecutionVerified"])
                self.assertEqual(len(data["agents"]), 4)
                self.assertTrue(all(not entry["workerVerified"]
                                    for entry in data["agents"]))

    def test_authentication_and_untrusted_host_origin_are_rejected(self):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        for headers, status_expected in (
            ({"Authorization": ""}, 401),
            ({"Authorization": "Bearer invalid"}, 401),
            ({"Host": "evil.example"}, 403),
            ({"Origin": "https://evil.example"}, 403),
        ):
            status, body, _ = self.request(msg, extras=headers)
            self.assertEqual(status, status_expected)
            self.assertNotIn(GATEWAY_TOKEN, json.dumps(body))
        ok, _, _ = self.request(msg, extras={"Origin": "https://chatgpt.com"})
        self.assertEqual(ok, 200)

    def test_rejects_bad_headers_routes_and_mutation_tools(self):
        msg = {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}
        for headers, expected in (
            ({"Content-Type": "text/plain"}, 415),
            ({"Accept": "application/json"}, 406),
            ({"MCP-Protocol-Version": "2099-01-01"}, 400),
        ):
            status, _, _ = self.request(msg, extras=headers)
            self.assertEqual(status, expected)
        self.assertEqual(self.request(msg, path="/debug")[0], 404)
        self.assertEqual(self.request(method="GET")[0], 405)
        self.assertEqual(self.request(method="DELETE")[0], 405)
        for bad in ([], {"jsonrpc": "2.0", "id": 1, "method": "run_shell"},
                    {"jsonrpc": "2.0", "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 1, "method": []},
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": []}}):
            self.assertEqual(self.request(bad)[0], 400)
        status, result, _ = self.request({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "run_shell", "arguments": {"command": "id"}},
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["error"]["code"], -32602)

    def test_duplicate_auth_headers_are_rejected(self):
        payload = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.gateway.server_port, timeout=4)
        try:
            connection.putrequest("POST", "/mcp")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Accept", ACCEPT)
            connection.putheader("Content-Length", str(len(payload)))
            connection.putheader("Authorization", "Bearer " + GATEWAY_TOKEN)
            connection.putheader("Authorization", "Bearer " + GATEWAY_TOKEN)
            connection.endheaders(payload)
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            connection.close()

    def test_startup_rejects_insecure_bindings_and_bad_origins(self):
        with self.assertRaises(ValueError):
            MCPHTTPGateway(("0.0.0.0", 0), GATEWAY_TOKEN)
        with self.assertRaises(ValueError):
            validate_token("short")
        with self.assertRaises(ValueError):
            allowed_origins_from_env("http://chatgpt.com")
        with self.assertRaises(ValueError):
            allowed_origins_from_env("https://chatgpt.com/path")
        self.assertEqual(allowed_origins_from_env(
            "https://chatgpt.com, https://example.org"),
            frozenset({"https://chatgpt.com", "https://example.org"}))


if __name__ == "__main__":
    unittest.main()
