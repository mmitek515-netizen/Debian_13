"""Integration contract tests: verify the actual Debian 13 API, not a mock UI backend.

These tests intentionally document the missing UI-to-API adapter. The UI expects
/api/v1/* and streaming chat; the current standalone runtime exposes /v1/*.
"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Debian13Server

TOKEN = "contract-test-token-at-least-32-characters-long"


class RuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = Debian13Server(("127.0.0.1", 0), {
            "api_token": TOKEN,
            "model_chat_url": "",
            "model_api_key": "",
            "model_name": "",
            "workspace": self.directory.name,
        })
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)
        self.directory.cleanup()

    def request(self, method, path, data=None, authorized=True):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        headers = {"Authorization": "Bearer " + TOKEN} if authorized else {}
        body = None if data is None else json.dumps(data)
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_health_and_authentication(self):
        status, body = self.request("GET", "/healthz", authorized=False)
        self.assertEqual((status, body["status"]), (200, "ok"))
        status, _ = self.request("GET", "/v1/profiles", authorized=False)
        self.assertEqual(status, 401)
        status, body = self.request("GET", "/v1/profiles")
        self.assertEqual(status, 200)
        self.assertEqual({p["id"] for p in body["profiles"]},
                         {"alex", "aria", "astyria", "aurelius"})
        self.assertTrue(all(p["active"] is False for p in body["profiles"]))

    def test_unconfigured_model_does_not_fabricate_chat(self):
        status, body = self.request("POST", "/v1/chat", {
            "profile": "aria", "message": "Status?"
        })
        self.assertEqual(status, 503)
        self.assertEqual(body["error"]["code"], "provider_not_configured")

    def test_ui_routes_require_adapter_not_yet_implemented(self):
        # This is a documented integration blocker, not a passing UI smoke test.
        for path in ("/api/v1/status", "/api/v1/agents", "/api/v1/tasks"):
            with self.subTest(path=path):
                status, _ = self.request("GET", path)
                self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
