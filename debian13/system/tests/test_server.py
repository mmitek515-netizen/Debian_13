import base64
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import Debian13Server, ollama_status, validate_ollama_base_url, validate_provider_url


TOKEN = "test-token-with-at-least-thirty-two-characters"


class ProviderHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.authorization = self.headers.get("Authorization")
        self.server.body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        body = json.dumps({"choices": [{"message": {"content": "Real test-provider response."}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class OllamaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"models": [{"name": "qwen3:0.6b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(payload)
        if payload["messages"][-1]["content"] == "Cancel me":
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                for index in range(100):
                    content = "first" if index == 0 else "next"
                    line = json.dumps({"message": {"content": content}, "done": False}).encode() + b"\n"
                    self.wfile.write(line)
                    self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError, OSError):
                self.server.stream_disconnected.set()
            return
        if payload["model"] != "qwen3:0.6b":
            body = json.dumps({"error": "model not found"}).encode()
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = b"".join([
            json.dumps({"message": {"content": "Hello "}, "done": False}).encode() + b"\n",
            json.dumps({"message": {"content": "from Ollama."}, "done": False}).encode() + b"\n",
            json.dumps({"done": True}).encode() + b"\n",
        ])
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class Debian13ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        (self.workspace / "hello.txt").write_text("hello Debian 13\n", encoding="utf-8")
        self.server = Debian13Server(("127.0.0.1", 0), {
            "api_token": TOKEN,
            "model_chat_url": "",
            "model_api_key": "",
            "model_name": "",
            "ollama_base_url": "",
            "ollama_model": "",
            "workspace": str(self.workspace),
        })
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = http.client.HTTPConnection(*self.server.server_address)

    def tearDown(self):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request_json(self, method, path, body=None, token=TOKEN):
        headers = {"Accept": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers["Content-Type"] = "application/json"
        self.connection.request(method, path, body=payload, headers=headers)
        response = self.connection.getresponse()
        self.last_retry_after = response.getheader("Retry-After")
        data = json.loads(response.read())
        return response.status, data

    def test_health_is_public_but_profiles_require_authentication(self):
        self.assertEqual(self.request_json("GET", "/healthz", token=None)[0], 200)
        status, _ = self.request_json("GET", "/v1/profiles", token=None)
        self.assertEqual(status, 401)
        status, data = self.request_json("GET", "/v1/profiles")
        self.assertEqual(status, 200)
        self.assertEqual([profile["id"] for profile in data["profiles"]], ["aria", "astyria", "aurelius", "alex"])
        self.assertTrue(all(profile["active"] is False for profile in data["profiles"]))

    def test_diagnostics_are_authenticated_and_do_not_disclose_secrets(self):
        self.assertEqual(self.request_json("GET", "/v1/diagnostics", token=None)[0], 401)
        self.assertEqual(self.request_json("GET", "/v1/diagnostics", token="invalid-token")[0], 401)
        self.server.config.update({
            "model_chat_url": "https://provider.example/v1/chat/completions",
            "model_api_key": "diagnostics-provider-secret",
            "model_name": "diagnostics-test-model",
        })
        status, data = self.request_json("GET", "/v1/diagnostics")
        self.assertEqual(status, 200)
        self.assertEqual(data["service"], "debian13-system")
        self.assertEqual(data["effectiveUid"], os.geteuid())
        self.assertTrue(data["workspaceWritable"])
        self.assertTrue(data["providerConfigured"])
        self.assertIsInstance(data["linuxSecurity"], dict)
        serialized = json.dumps(data)
        self.assertNotIn(TOKEN, serialized)
        self.assertNotIn("diagnostics-provider-secret", serialized)
        self.assertNotIn("diagnostics-test-model", serialized)

    def test_terminal_executes_allowlisted_argv_without_shell_or_secret_inheritance(self):
        status, data = self.request_json("POST", "/v1/terminal", {"command": "cat hello.txt"})
        self.assertEqual(status, 200)
        self.assertEqual(data["stdout"], "hello Debian 13\n")
        self.assertEqual(data["exitCode"], 0)

    def test_terminal_rejects_shells_unknown_commands_and_paths_outside_workspace(self):
        self.assertEqual(self.request_json("POST", "/v1/terminal", {"command": "sh -c id"})[0], 403)
        status, data = self.request_json("POST", "/v1/terminal", {"command": "cat ../../etc/passwd"})
        self.assertEqual(status, 403)
        self.assertEqual(data["error"]["code"], "path_outside_workspace")
        (self.workspace / "outside.txt").symlink_to("/etc/passwd")
        self.assertEqual(self.request_json("POST", "/v1/terminal", {"command": "cat outside.txt"})[0], 403)

    def test_terminal_output_is_bounded(self):
        (self.workspace / "large.txt").write_bytes(b"x" * (1024 * 1024 + 1))
        status, data = self.request_json("POST", "/v1/terminal", {"command": "cat large.txt"})
        self.assertEqual(status, 413)
        self.assertEqual(data["error"]["code"], "output_too_large")

    def test_chat_rejects_non_string_profile(self):
        status, data = self.request_json("POST", "/v1/chat", {"profile": [], "message": "test"})
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["code"], "invalid_profile")

    def test_chat_fails_closed_without_a_model_provider(self):
        status, data = self.request_json("POST", "/v1/chat", {"profile": "aria", "message": "test"})
        self.assertEqual(status, 503)
        self.assertEqual(data["error"]["code"], "provider_not_configured")

    def test_chat_calls_configured_provider_with_selected_profile(self):
        provider = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
        provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
        provider_thread.start()
        try:
            self.server.config.update({
                "model_chat_url": f"http://127.0.0.1:{provider.server_port}/v1/chat/completions",
                "model_api_key": "provider-secret",
                "model_name": "integration-test-model",
            })
            status, data = self.request_json("POST", "/v1/chat", {
                "profile": "aurelius",
                "message": "Review this test.",
            })
            self.assertEqual(status, 200)
            self.assertEqual(data["content"], "Real test-provider response.")
            self.assertEqual(data["profile"], "aurelius")
            self.assertEqual(provider.authorization, "Bearer " + self.server.config["model_api_key"])
            self.assertIn("not aria", provider.body["messages"][0]["content"].lower())
        finally:
            provider.shutdown()
            provider.server_close()
            provider_thread.join(timeout=2)

    def test_ollama_native_stream_persists_context_and_reports_private_status(self):
        provider = ThreadingHTTPServer(("127.0.0.1", 0), OllamaHandler)
        provider.requests = []
        worker = threading.Thread(target=provider.serve_forever, daemon=True)
        worker.start()
        try:
            self.server.config.update({
                "ollama_base_url": f"http://127.0.0.1:{provider.server_port}",
                "ollama_model": "qwen3:0.6b",
            })
            status, state = self.request_json("GET", "/api/v1/ollama")
            self.assertEqual(status, 200)
            self.assertEqual(state, {"status": "model_available", "model_available": True})
            self.assertNotIn("qwen3:0.6b", json.dumps(state))
            connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
            try:
                body = {"agent": "all", "message": "First turn"}
                connection.request("POST", "/api/v1/chat/stream", body=json.dumps(body),
                                   headers={"Authorization": "Bearer " + TOKEN,
                                            "Content-Type": "application/json"})
                reply = connection.getresponse()
                events = reply.read().decode("utf-8")
                self.assertEqual(reply.status, 200)
                self.assertTrue(reply.getheader("Content-Type").startswith("text/event-stream"))
                self.assertIn('"source": "ollama"', events)
                self.assertIn('"session_id": "', events)
                self.assertIn('"text": "Hello "', events)
                self.assertIn('"text": "from Ollama."', events)
                self.assertIn('event: done\n', events)
                meta = json.loads(events.split("data: ", 1)[1].splitlines()[0])
                session_id = meta["session_id"]
                self.assertEqual(len(meta["disconnected_agents"]), 4)
                self.assertEqual(meta["channel"], "all")
                runtime_status = self.request_json("GET", "/api/v1/status")[1]
                self.assertEqual(runtime_status["model"]["status"], "model_available")
                self.assertNotIn("qwen3:0.6b", json.dumps(runtime_status))

                connection.close()
                connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
                body = {"agent": "ollama", "message": "Second turn", "session_id": session_id}
                connection.request("POST", "/api/v1/chat/stream", body=json.dumps(body),
                                   headers={"Authorization": "Bearer " + TOKEN,
                                            "Content-Type": "application/json"})
                reply = connection.getresponse()
                reply.read()
                context = provider.requests[1]["messages"]
                self.assertEqual(context[-3]["content"], "First turn")
                self.assertEqual(context[-2]["content"], "Hello from Ollama.")
                self.assertEqual(context[-1]["content"], "Second turn")
                saved = self.request_json("GET", f"/api/v1/sessions/{session_id}/messages")[1]
                self.assertEqual([item["role"] for item in saved["messages"]],
                                 ["user", "assistant", "user", "assistant"])
                self.assertEqual([item["channel"] for item in saved["messages"]],
                                 ["all", "all", "ollama", "ollama"])
                self.assertEqual(len(self.request_json("GET", "/api/v1/sessions")[1]["sessions"]), 1)
            finally:
                connection.close()
        finally:
            provider.shutdown()
            provider.server_close()
            worker.join(timeout=3)

    def test_original_agent_chat_fails_closed_and_logs_attempt(self):
        status, response = self.request_json("POST", "/api/v1/chat/stream", {
            "agent": "aria", "message": "Do not fake a response.",
        })
        self.assertEqual(status, 503)
        self.assertEqual(response["error"]["code"], "agent_disconnected")
        status, response = self.request_json("POST", "/api/v1/chat/stream", {
            "agent": "all", "message": "No connected channels.",
        })
        self.assertEqual(status, 503)
        self.assertEqual(response["error"]["code"], "agent_disconnected")
        attempts = self.request_json("GET", "/api/v1/original-agent-attempts")[1]["attempts"]
        self.assertEqual(
            {attempt["agent"] for attempt in attempts},
            {"aria", "alex", "astyria", "aurelius"},
        )
        self.assertTrue(all(attempt["status"] == "agent_disconnected" for attempt in attempts))

    def test_real_vision_payload_to_provider_and_invalid_input_rejected(self):
        provider = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
        worker = threading.Thread(target=provider.serve_forever, daemon=True)
        worker.start()
        try:
            self.server.config.update({
                "model_chat_url": f"http://127.0.0.1:{provider.server_port}/v1/chat/completions",
                "model_api_key": "fixture-provider-key",
                "model_name": "fixture-text-model",
                "vision_model_name": "llama3.2-vision:11b",
            })
            photo = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"test-image-bytes").decode()
            status, result = self.request_json("POST", "/v1/vision", {
                "profile": "aria", "message": "Describe this image.",
                "image": {"mime_type": "image/png", "base64": photo},
            })
            self.assertEqual(status, 200)
            self.assertEqual(result["model"], "llama3.2-vision:11b")
            self.assertEqual(provider.body["model"], "llama3.2-vision:11b")
            segments = provider.body["messages"][1]["content"]
            self.assertEqual(segments[0]["text"], "Describe this image.")
            self.assertTrue(segments[1]["image_url"]["url"].startswith("data:image/png;base64,"))
            status, data = self.request_json("POST", "/v1/vision", {
                "profile": "aria", "message": "Check",
                "image": {"mime_type": "image/png", "base64": "%%bad-base64"},
            })
            self.assertEqual(status, 400)
            self.assertEqual(data["error"]["code"], "invalid_image")
            status, _ = self.request_json("POST", "/v1/vision", {
                "profile": "aria", "message": "Check",
                "image": {"mime_type": "image/gif", "base64": photo},
            })
            self.assertEqual(status, 400)
        finally:
            provider.shutdown()
            provider.server_close()
            worker.join(timeout=3)

    def test_provider_url_rejects_untrusted_schemes_and_non_loopback_http(self):
        with self.assertRaises(ValueError):
            validate_provider_url("http://example.com/v1/chat/completions")
        with self.assertRaises(ValueError):
            validate_provider_url("******example.com/v1/chat/completions")

    def test_ollama_url_is_server_configured_and_restricted_to_trusted_hosts(self):
        self.assertEqual(validate_ollama_base_url("http://127.0.0.1:11434"), "http://127.0.0.1:11434")
        with patch.dict(os.environ, {"DEBIAN13_ALLOW_INTERNAL_OLLAMA": "1"}):
            self.assertEqual(validate_ollama_base_url("http://ollama:11434"), "http://ollama:11434")
        for value in ("http://example.com:11434", "http://ollama:80", "******127.0.0.1:11434"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_ollama_base_url(value)

    def test_ollama_status_reports_a_friendly_connection_refused_state(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        status = ollama_status({
            "ollama_base_url": f"http://127.0.0.1:{port}",
            "ollama_model": "qwen3:0.6b",
        })
        self.assertEqual(status["status"], "connection_refused")
        self.assertFalse(status["model_available"])

    def test_ollama_chat_reports_model_missing_and_connection_refused(self):
        provider = ThreadingHTTPServer(("127.0.0.1", 0), OllamaHandler)
        provider.requests = []
        worker = threading.Thread(target=provider.serve_forever, daemon=True)
        worker.start()
        try:
            self.server.config.update({
                "ollama_base_url": f"http://127.0.0.1:{provider.server_port}",
                "ollama_model": "qwen3:9b",
            })
            status, data = self.request_json("POST", "/api/v1/chat/stream", {
                "agent": "ollama", "message": "Test missing model.",
            })
            self.assertEqual(status, 503)
            self.assertEqual(data["error"]["code"], "model_not_found")
        finally:
            provider.shutdown()
            provider.server_close()
            worker.join(timeout=3)

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        self.server.config.update({
            "ollama_base_url": f"http://127.0.0.1:{port}",
            "ollama_model": "qwen3:0.6b",
        })
        status, data = self.request_json("POST", "/api/v1/chat/stream", {
            "agent": "ollama", "message": "Test unavailable server.",
        })
        self.assertEqual(status, 503)
        self.assertEqual(data["error"]["code"], "connection_refused")

    def test_aborting_stream_closes_the_upstream_model_connection(self):
        provider = ThreadingHTTPServer(("127.0.0.1", 0), OllamaHandler)
        provider.requests = []
        provider.stream_disconnected = threading.Event()
        worker = threading.Thread(target=provider.serve_forever, daemon=True)
        worker.start()
        self.server.config.update({
            "ollama_base_url": f"http://127.0.0.1:{provider.server_port}",
            "ollama_model": "qwen3:0.6b",
        })
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            body = json.dumps({"agent": "ollama", "message": "Cancel me"})
            connection.request("POST", "/api/v1/chat/stream", body=body,
                               headers={"Authorization": "Bearer " + TOKEN,
                                        "Content-Type": "application/json"})
            reply = connection.getresponse()
            self.assertEqual(reply.status, 200)
            while True:
                line = reply.readline().decode("utf-8")
                if line == "event: delta\n":
                    reply.readline()
                    self.assertEqual(reply.readline(), b"\n")
                    break
                if not line:
                    self.fail("stream ended before first delta")
                if line.startswith("data: "):
                    reply.readline()
            reply.close()
            connection.close()
            self.assertTrue(provider.stream_disconnected.wait(timeout=4))
        finally:
            connection.close()
            provider.shutdown()
            provider.server_close()
            worker.join(timeout=3)

    def test_rate_limit_returns_429(self):
        self.server.config["rate_limit"] = 2
        self.assertEqual(self.request_json("GET", "/v1/profiles")[0], 200)
        self.assertEqual(self.request_json("GET", "/v1/profiles")[0], 200)
        status, _ = self.request_json("GET", "/v1/profiles")
        self.assertEqual(status, 429)
        self.assertTrue(self.last_retry_after.isdigit())


if __name__ == "__main__":
    unittest.main()
