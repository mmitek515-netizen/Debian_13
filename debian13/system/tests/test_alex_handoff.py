"""Live loopback tests: original Alex handoff fails closed without capabilities.

The test server deliberately mimics a compatible original-Alex endpoint;
it is not evidence of any deployed or autonomous real Alex agent.
"""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Debian13Server

TOKEN = "alex-test-operator-token-at-least-thirty-two-characters"
EXTERNAL_TOKEN = "original-alex-test-token-longer-than-thirty-two-characters"
TASK = {
    "agent": "alex", "kind": "development", "title": "Verify test dispatch",
    "description": "Prepare PR with tests for Debian 13. No purchases.",
}


class OriginalAlexDouble(BaseHTTPRequestHandler):
    capability = True
    accepted = True
    calls = []

    def log_message(self, *_args):
        pass

    def _respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/api/agent-tasks/capabilities":
            self._respond(404, {"error": "not_found"})
            return
        if not type(self).capability:
            self._respond(404, {"error": "unsupported"})
            return
        self._respond(200, {
            "agent": "Alex",
            "sourceRepository": "u6930438163-code/AI_Studio_BastillaOS",
            "protocolVersion": 1,
            "capabilities": ["debian13_issue_to_pr"],
        })

    def do_POST(self):
        if self.path != "/api/agent-tasks/submit":
            self._respond(404, {"error": "not_found"})
            return
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls.append({
            "path": self.path, "body": data,
            "authorization": self.headers.get("Authorization"),
            "key": self.headers.get("Idempotency-Key"),
        })
        self._respond(202, {
            "accepted": type(self).accepted,
            "agent": "Alex",
            "capability": "debian13_issue_to_pr",
            "taskId": "alex-original-task-123",
        })


class OriginalAlexHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.remote = ThreadingHTTPServer(("127.0.0.1", 0), OriginalAlexDouble)
        cls.remote_thread = threading.Thread(target=cls.remote.serve_forever, daemon=True)
        cls.remote_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.remote.shutdown()
        cls.remote.server_close()
        cls.remote_thread.join(timeout=5)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        OriginalAlexDouble.calls = []
        OriginalAlexDouble.capability = True
        OriginalAlexDouble.accepted = True
        self.env = patch.dict(os.environ, {
            "ALEX_EXISTING_API_URL": f"http://127.0.0.1:{self.remote.server_port}/api",
            "ALEX_EXISTING_API_TOKEN": EXTERNAL_TOKEN,
            "ALEX_ALLOW_TASK_DISPATCH": "1",
        })
        self.env.start()
        self.api = Debian13Server(("127.0.0.1", 0), {
            "api_token": TOKEN, "model_chat_url": "", "model_api_key": "",
            "model_name": "", "workspace": self.temp.name,
        })
        self.api_thread = threading.Thread(target=self.api.serve_forever, daemon=True)
        self.api_thread.start()

    def tearDown(self):
        self.api.shutdown()
        self.api.server_close()
        self.api_thread.join(timeout=5)
        self.env.stop()
        self.temp.cleanup()

    def call(self, method, path, data=None, token=TOKEN):
        client = http.client.HTTPConnection(*self.api.server_address, timeout=7)
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            client.request(method, path,
                           body=json.dumps(data) if data is not None else None,
                           headers=headers)
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def task_id(self):
        response = self.call("POST", "/api/v1/tasks", TASK)
        self.assertEqual(response[0], 201)
        return response[1]["task"]["id"]

    def test_success_requires_real_capabilities_then_records_one_receipt(self):
        task_id = self.task_id()
        status, state = self.call("GET", "/api/v1/alex/capabilities")
        self.assertEqual(status, 200)
        self.assertTrue(state["alex"]["supported"])
        self.assertFalse(state["alex"]["agentRuntimeVerified"])
        status, sent = self.call("POST", f"/api/v1/tasks/{task_id}/dispatch")
        self.assertEqual(status, 202)
        self.assertFalse(sent["executionStarted"])
        self.assertFalse(sent["agentExecutionVerified"])
        self.assertEqual(sent["alexSubmission"]["remoteTaskId"], "alex-original-task-123")
        self.assertEqual(OriginalAlexDouble.calls[0]["key"], task_id)
        self.assertEqual(OriginalAlexDouble.calls[0]["authorization"],
                         "Bearer " + EXTERNAL_TOKEN)
        posted = OriginalAlexDouble.calls[0]["body"]
        self.assertEqual(posted["agent"], "Alex")
        self.assertEqual(posted["task"]["targetRepository"],
                         "mmitek515-netizen/Debian_13")
        self.assertEqual(posted["mode"], "pull_request_proposal")
        self.assertFalse(posted["purchaseAuthorized"])
        self.assertFalse(posted["autoMerge"])
        self.assertEqual(self.call("GET", f"/api/v1/tasks/{task_id}")[1]["alexSubmission"]["remoteTaskId"],
                         "alex-original-task-123")
        status, replay = self.call("POST", f"/api/v1/tasks/{task_id}/dispatch")
        self.assertEqual(status, 200)
        self.assertEqual(len(OriginalAlexDouble.calls), 1)
        self.assertEqual(self.call("POST", f"/api/v1/tasks/{task_id}/cancel")[0], 409)
        events = self.call("GET", "/api/v1/events")[1]["events"]
        self.assertEqual(events[0]["type"], "task_accepted_by_remote_api")

    def test_missing_capability_refuses_without_posting(self):
        OriginalAlexDouble.capability = False
        task_id = self.task_id()
        status, response = self.call("GET", "/api/v1/alex/capabilities")
        self.assertEqual(status, 200)
        self.assertFalse(response["alex"]["supported"])
        status, response = self.call("POST", f"/api/v1/tasks/{task_id}/dispatch")
        self.assertEqual(status, 409)
        self.assertIn(response["error"]["code"], {"unsupported_capability"})
        self.assertEqual(OriginalAlexDouble.calls, [])

    def test_explicit_opt_in_is_required_and_secrets_not_disclosed(self):
        task_id = self.task_id()
        with patch.dict(os.environ, {"ALEX_ALLOW_TASK_DISPATCH": "0"}):
            state = self.call("GET", "/api/v1/alex/capabilities")[1]["alex"]
            self.assertFalse(state["supported"])
            self.assertEqual(state["reason"], "dispatch_not_enabled")
            status, data = self.call("POST", f"/api/v1/tasks/{task_id}/dispatch")
        self.assertEqual(status, 409)
        self.assertEqual(data["error"]["code"], "dispatch_not_enabled")
        self.assertNotIn(EXTERNAL_TOKEN, json.dumps(data))
        self.assertEqual(OriginalAlexDouble.calls, [])

    def test_missing_authorization_does_not_contact_original_alex(self):
        task_id = self.task_id()
        self.assertEqual(self.call("POST", f"/api/v1/tasks/{task_id}/dispatch",
                                   token=None)[0], 401)
        self.assertEqual(OriginalAlexDouble.calls, [])

    def test_alex_must_confirm_acceptance_not_just_http_202(self):
        task_id = self.task_id()
        OriginalAlexDouble.accepted = False
        status, result = self.call("POST", f"/api/v1/tasks/{task_id}/dispatch")
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "submission_unverified")
        self.assertIsNone(self.call("GET", f"/api/v1/tasks/{task_id}")[1]["alexSubmission"])
        self.assertEqual(len(OriginalAlexDouble.calls), 1)

    def test_other_agent_cannot_be_dispatched_as_alex(self):
        other = dict(TASK, agent="aria")
        task_id = self.call("POST", "/api/v1/tasks", other)[1]["task"]["id"]
        status, _ = self.call("POST", f"/api/v1/tasks/{task_id}/dispatch")
        self.assertEqual(status, 409)
        self.assertEqual(OriginalAlexDouble.calls, [])


if __name__ == "__main__":
    unittest.main()
