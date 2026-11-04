"""HTTP-level checks for the SVL command API."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Debian13Server

TEST_TOKEN = "test-only-token-longer-than-thirty-two-chars"


class SVLHttpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = Debian13Server(("127.0.0.1", 0), {
            "api_token": TEST_TOKEN,
            "model_chat_url": "",
            "model_api_key": "",
            "model_name": "",
            "workspace": self.directory.name,
        })
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def call(self, command, authorized=True):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["Authorization"] = "Bearer " + TEST_TOKEN
        try:
            conn.request("POST", "/api/v1/svl/command",
                         body=json.dumps({"command": command}), headers=headers)
            reply = conn.getresponse()
            return reply.status, json.loads(reply.read())
        finally:
            conn.close()

    def test_authentication(self):
        self.assertEqual(self.call("status", authorized=False)[0], 401)

    def test_status(self):
        status, data = self.call("status")
        self.assertEqual(status, 200)
        self.assertEqual(data["processor"], "SVL")
        self.assertEqual(data["result"]["Compact_Metric_C"], 2.5)

    def test_reject_unrecognized_command(self):
        status, data = self.call("unknown")
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["code"], "svl_invalid_command")

    def test_integration_status_is_not_overclaimed(self):
        status, data = self.call("integracje")
        self.assertEqual(status, 200)
        self.assertTrue(all(not item["connected"] for item in data["result"]["integrations"]))


if __name__ == "__main__":
    unittest.main()
