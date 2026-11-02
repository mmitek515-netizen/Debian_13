"""Integration tests for the original Alex registry read-only MCP bridge."""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import alex_bridge
import mcp_server

SECRET = "alex-bridge-test-secret-not-in-source"


class RegistryHandler(BaseHTTPRequestHandler):
    received_auth = None
    response_kind = "ok"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        type(self).received_auth = self.headers.get("Authorization")
        if self.path != "/api/agent-tasks":
            self.send_error(404)
            return
        if type(self).response_kind == "redirect":
            self.send_response(302)
            self.send_header("Location", "https://untrusted.example/steal")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps({
            "success": True,
            "tasks": [
                {"id": "alex-123", "agent": "Alex", "title": "Debian 13 architecture",
                 "status": "running", "createdAt": "2026-11-02T12:00:00Z",
                 "artifact": {"path": "/private/agent-data"}},
                {"id": "aria-124", "agent": "Aria", "title": "SECRET OTHER AGENT",
                 "status": "completed", "logs": ["private data"]},
            ],
            "stats": {"running": 1, "total": 2},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ExistingAlexBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), RegistryHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        RegistryHandler.response_kind = "ok"
        RegistryHandler.received_auth = None
        self.url = f"http://127.0.0.1:{self.server.server_port}/api"
        self.env = patch.dict(os.environ, {
            "ALEX_EXISTING_API_URL": self.url,
            "ALEX_EXISTING_API_TOKEN": SECRET,
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_reads_original_registry_and_filters_other_agents(self):
        result = alex_bridge.read_existing_alex("alex_existing_tasks")
        self.assertTrue(result["registryReachable"])
        self.assertFalse(result["alexWorkerVerified"])
        self.assertEqual(result["sourceRepository"],
                         "u6930438163-code/AI_Studio_BastillaOS")
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["id"], "alex-123")
        self.assertEqual(result["tasks"][0]["status"], "running")
        self.assertNotIn("logs", result["tasks"][0])
        self.assertNotIn("SECRET OTHER AGENT", json.dumps(result))
        self.assertNotIn("/private/", json.dumps(result))
        self.assertEqual(RegistryHandler.received_auth, "Bearer " + SECRET)

    def test_status_does_not_claim_agent_llm_has_started(self):
        result = alex_bridge.read_existing_alex("alex_existing_status")
        self.assertTrue(result["registryReachable"])
        self.assertEqual(result["reportedRunningTasks"], 1)
        self.assertFalse(result["alexWorkerVerified"])

    def test_mcp_tool_dispatch_uses_existing_instance_not_a_role(self):
        answer = mcp_server.response({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "alex_existing_status", "arguments": {}},
        })
        self.assertFalse(answer["result"]["isError"])
        result = json.loads(answer["result"]["content"][0]["text"])
        self.assertTrue(result["registryReachable"])

    def test_unconfigured_endpoint_is_explicitly_offline(self):
        with patch.dict(os.environ, {"ALEX_EXISTING_API_URL": "",
                                     "BASTILLA_REMOTE_API_URL": ""}):
            result = alex_bridge.read_existing_alex("alex_existing_status")
        self.assertFalse(result["configured"])
        self.assertFalse(result["registryReachable"])

    def test_rejects_remote_plaintext_and_url_credentials(self):
        for invalid in ("http://example.org/api", "https://user:pass@example.org/api",
                        "https://example.org/api?token=foo", "ftp://example.org/api",
                        "https://example.org/private"):
            with self.subTest(url=invalid), patch.dict(
                    os.environ, {"ALEX_EXISTING_API_URL": invalid}):
                with self.assertRaises(ValueError):
                    alex_bridge.existing_api_base()

    def test_redirect_does_not_forward_token(self):
        RegistryHandler.response_kind = "redirect"
        result = mcp_server.response({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "alex_existing_tasks", "arguments": {}},
        })
        self.assertTrue(result["result"]["isError"])
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn(self.url, json.dumps(result))

    def test_mutation_tools_do_not_exist(self):
        tools = mcp_server.response({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {item["name"] for item in tools["result"]["tools"]}
        self.assertEqual(names.intersection({"alex_run_task", "alex_buy", "alex_write"}), set())
        self.assertTrue({"alex_existing_status", "alex_existing_tasks"}.issubset(names))


if __name__ == "__main__":
    unittest.main()
