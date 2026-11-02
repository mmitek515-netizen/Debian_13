"""Real authenticated HTTP and persistence checks for the Work task ledger."""
import http.client
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import Debian13Server
from work_store import WorkStore

TOKEN = "long-test-token-for-the-work-ledger-1234567"
TASK = {"agent": "alex", "kind": "development",
        "title": "Build Debian 13", "description": "Review API and add tests. No purchases."}


class WorkLedgerApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.api = Debian13Server(("127.0.0.1", 0), {
            "api_token": TOKEN,
            "model_chat_url": "",
            "model_api_key": "",
            "model_name": "",
            "workspace": str(self.workspace),
        })
        self.thread = threading.Thread(target=self.api.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.api.shutdown()
        self.api.server_close()
        self.thread.join(timeout=4)
        self.temp.cleanup()

    def call(self, method, path, body=None, token=TOKEN):
        connection = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=5)
        headers = {"Accept": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        payload = json.dumps(body) if body is not None else None
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_tasks_persist_and_are_not_executed_by_agent(self):
        status, created = self.call("POST", "/api/v1/tasks", TASK)
        self.assertEqual(status, 201)
        self.assertFalse(created["executionStarted"])
        task = created["task"]
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["agent"], "alex")
        self.assertEqual(task["execution"], "not_started")
        self.assertEqual(task["requires_approval"], 1)
        self.assertEqual(len(self.call("GET", "/api/v1/tasks")[1]["tasks"]), 1)
        self.assertEqual(self.call("GET", "/api/v1/tasks/" + task["id"])[1]["task"]["id"], task["id"])
        events = self.call("GET", "/api/v1/events")[1]["events"]
        self.assertEqual([event["type"] for event in events], ["task_queued"])
        self.assertEqual(stat.S_IMODE(os.stat(self.api.work_store.db_path).st_mode), 0o600)
        self.assertEqual(WorkStore(self.workspace).get_task(task["id"])["status"], "queued")

    def test_cancel_is_audited_and_idempotent(self):
        task = self.call("POST", "/api/v1/tasks", TASK)[1]["task"]
        status, result = self.call("POST", "/api/v1/tasks/" + task["id"] + "/cancel")
        self.assertEqual(status, 200)
        self.assertEqual(result["task"]["status"], "cancelled")
        self.assertEqual(result["task"]["execution"], "not_started")
        status, result = self.call("POST", "/api/v1/tasks/" + task["id"] + "/cancel")
        self.assertEqual(status, 200)
        events = self.call("GET", "/api/v1/events")[1]["events"]
        self.assertEqual([event["type"] for event in events],
                         ["task_cancelled", "task_queued"])
        self.assertEqual(WorkStore(self.workspace).get_task(task["id"])["status"], "cancelled")

    def test_auth_and_input_rejections(self):
        self.assertEqual(self.call("POST", "/api/v1/tasks", TASK, token=None)[0], 401)
        self.assertEqual(self.call("GET", "/api/v1/tasks", token=None)[0], 401)
        self.assertEqual(self.call("POST", "/api/v1/tasks", {**TASK, "agent": "root"})[0], 400)
        self.assertEqual(self.call("POST", "/api/v1/tasks", {**TASK, "kind": "run_shell"})[0], 400)
        self.assertEqual(self.call("POST", "/api/v1/tasks", {**TASK, "description": "x" * 2001})[0], 400)
        self.assertEqual(self.call("POST", "/api/v1/tasks", {**TASK, "extra": "unexpected"})[0], 400)
        self.assertEqual(self.call("GET", "/api/v1/tasks/not-a-valid-uuid")[0], 404)
        self.assertEqual(self.call("GET", "/api/v1/tasks")[1]["tasks"], [])

    def test_cancel_unknown_task_is_not_success(self):
        missing = "123e4567-e89b-42d3-a456-426614174001"
        status, response = self.call("POST", f"/api/v1/tasks/{missing}/cancel")
        self.assertEqual(status, 404)
        self.assertEqual(response["error"]["code"], "task_not_found")


if __name__ == "__main__":
    unittest.main()
