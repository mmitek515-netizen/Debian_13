"""Exercise the private launch and probe without downloading a model or using GitHub."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request

REPO = Path(__file__).resolve().parents[3]
CHECK = REPO / "debian13/system/check_priority_runtime.py"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class PriorityRuntimeTests(unittest.TestCase):
    def environment(self, tmp):
        env = os.environ.copy()
        for key in ("DEBIAN13_API_TOKEN", "MODEL_CHAT_URL", "MODEL_API_KEY", "MODEL_NAME",
                    "DEBIAN13_LOCAL_OLLAMA", "OLLAMA_MODEL", "OLLAMA_VISION_MODEL"):
            env.pop(key, None)
        env.update(DEBIAN13_STATE_DIR=str(Path(tmp) / "state"),
                   WORKSPACE_DIR=str(Path(tmp) / "workspace"),
                   DEBIAN13_API_PORT=str(free_port()), DEBIAN13_UI_PORT=str(free_port()))
        while env["DEBIAN13_UI_PORT"] == env["DEBIAN13_API_PORT"]:
            env["DEBIAN13_UI_PORT"] = str(free_port())
        return env

    def test_compose_launch_uses_small_default_and_honours_model_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.environment(tmp)
            fakebin = Path(tmp) / "bin"
            fakebin.mkdir()
            docker = fakebin / "docker"
            # This fake records only the chosen model; it never invokes Docker or a model.
            docker.write_text('#!/bin/sh\ncase "$*" in *" up "*) printf "%s" "$OLLAMA_MODEL" > "$MODEL_RECORD";; esac\n')
            docker.chmod(0o755)
            env.update(PATH=str(fakebin) + os.pathsep + env["PATH"], MODEL_RECORD=str(Path(tmp) / "model"))
            for selected, expected in ((None, "qwen2.5-coder:1.5b"), ("llama3.2:3b", "llama3.2:3b")):
                if selected:
                    env["OLLAMA_MODEL"] = selected
                else:
                    env.pop("OLLAMA_MODEL", None)
                launch = subprocess.run(["bash", "debian13/start-ai-session.sh"], cwd=REPO, env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(launch.returncode, 0, launch.stderr)
                self.assertEqual(Path(env["MODEL_RECORD"]).read_text(), expected)
                self.assertTrue((Path(env["DEBIAN13_STATE_DIR"]) / "operator-token").is_file())

    def test_real_local_gui_terminal_and_mcp_fail_closed_without_ollama(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.environment(tmp)
            app = subprocess.Popen(["bash", "debian13/start-local.sh"], cwd=REPO, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                url = f'http://127.0.0.1:{env["DEBIAN13_UI_PORT"]}/api/v1/status'
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(url, timeout=.3) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        if app.poll() is not None:
                            self.fail("Local app stopped before it became ready")
                        time.sleep(.1)
                else:
                    self.fail("Local app did not become ready")
                result = subprocess.run(["python3", str(CHECK)], cwd=REPO, env=env,
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("PASS: GUI", result.stdout)
                self.assertIn("REST and MCP reject anonymous access (401)", result.stdout)
                self.assertIn("PASS: terminal", result.stdout)
                self.assertIn("PASS: local authenticated MCP", result.stdout)
                self.assertIn("Ollama inference: NOT TESTED", result.stdout)
                result = subprocess.run(["python3", str(CHECK), "--ollama-chat"], cwd=REPO, env=env,
                                        capture_output=True, text=True, timeout=20)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("no model request was sent", result.stderr)
                self.assertNotIn("received an Ollama reply", result.stdout)
            finally:
                app.terminate()
                try:
                    app.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    app.kill()
                    app.wait()

    def test_four_profile_chat_probe_with_local_provider_fixture(self):
        class Fixture(BaseHTTPRequestHandler):
            requests = 0

            def do_POST(self):
                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if payload.get("model") != "fixture-model":
                    self.send_error(400)
                    return
                Fixture.requests += 1
                body = json.dumps({"choices": [{"message": {"content": "fixture response"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        try:
            provider = ThreadingHTTPServer(("127.0.0.1", 11434), Fixture)
        except OSError:
            self.skipTest("The fixture requires local port 11434")
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env = self.environment(tmp)
                env.update(DEBIAN13_LOCAL_OLLAMA="1", OLLAMA_MODEL="fixture-model")
                app = subprocess.Popen(["bash", "debian13/start-local.sh"], cwd=REPO, env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    url = f'http://127.0.0.1:{env["DEBIAN13_UI_PORT"]}/api/v1/status'
                    for _ in range(100):
                        try:
                            with urllib.request.urlopen(url, timeout=.3) as response:
                                if response.status == 200:
                                    break
                        except OSError:
                            if app.poll() is not None:
                                self.fail("Local app stopped before it became ready")
                            time.sleep(.1)
                    else:
                        self.fail("Local app did not become ready")
                    result = subprocess.run(["python3", str(CHECK), "--ollama-chat"], cwd=REPO, env=env,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.count("chat profile received an Ollama reply"), 4)
                    self.assertEqual(Fixture.requests, 4)
                    self.assertIn("Original agent workers, remote ChatGPT MCP and Issue-to-PR: NOT VERIFIED", result.stdout)
                finally:
                    app.terminate()
                    try:
                        app.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        app.kill()
                        app.wait()
        finally:
            provider.shutdown()
            provider.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
