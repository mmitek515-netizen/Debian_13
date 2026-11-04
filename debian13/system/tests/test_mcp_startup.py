"""Integration checks for opt-in MCP startup from the Debian 13 console launcher."""
from __future__ import annotations

import json
import os
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
START = ROOT / "debian13" / "start-local.sh"
PREFLIGHT = ROOT / "debian13" / "system" / "mcp_preflight.py"
API_TOKEN = "test-debian13-api-secret-must-be-32-chars"


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class MCPStartupTests(unittest.TestCase):
    def test_start_local_opt_in_mcp_with_separate_persisted_token(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / "state"
            workspace = Path(root) / "workspace"
            ports: set[int] = set()
            while len(ports) < 3:
                ports.add(available_port())
            api_port, ui_port, mcp_port = sorted(ports)
            env = {
                **os.environ,
                "DEBIAN13_STATE_DIR": str(state),
                "WORKSPACE_DIR": str(workspace),
                "DEBIAN13_API_TOKEN": API_TOKEN,
                "DEBIAN13_API_PORT": str(api_port),
                "DEBIAN13_UI_PORT": str(ui_port),
                "DEBIAN13_MCP_GATEWAY_PORT": str(mcp_port),
                "DEBIAN13_ENABLE_MCP_HTTP": "1",
            }
            for key in ("DEBIAN13_MCP_GATEWAY_TOKEN", "DEBIAN13_SYSTEM_API_URL",
                        "MODEL_CHAT_URL", "MODEL_API_KEY", "MODEL_NAME"):
                env.pop(key, None)

            def run_and_probe() -> str:
                with tempfile.TemporaryFile() as output:
                    process = subprocess.Popen(
                        ["bash", str(START)], cwd=ROOT, env=env,
                        stdout=output, stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    try:
                        deadline = time.monotonic() + 14
                        token_file = state / "mcp-gateway-token"
                        token = ""
                        while time.monotonic() < deadline:
                            if process.poll() is not None:
                                output.seek(0)
                                self.fail("Debian 13 launcher exited: " +
                                          output.read().decode("utf-8", "replace")[-3000:])
                            if token_file.is_file():
                                token = token_file.read_text().strip()
                                if len(token) >= 32:
                                    request = urllib.request.Request(
                                        "http://127.0.0.1:" + str(mcp_port) + "/mcp",
                                        data=json.dumps({
                                            "jsonrpc": "2.0", "id": 42,
                                            "method": "tools/list",
                                        }).encode("utf-8"),
                                        headers={
                                            "Content-Type": "application/json",
                                            "Accept": "application/json, text/event-stream",
                                            "MCP-Protocol-Version": "2025-11-25",
                                            "Authorization": "Bearer " + token,
                                        },
                                        method="POST",
                                    )
                                    try:
                                        with urllib.request.urlopen(request, timeout=1) as res:
                                            reply = json.load(res)
                                            self.assertEqual(res.status, 200)
                                            tools = {item["name"] for item in reply["result"]["tools"]}
                                            self.assertIn("debian13_work_tasks", tools)
                                            self.assertIn("debian13_original_agents", tools)
                                        break
                                    except (urllib.error.URLError, OSError, TimeoutError):
                                        pass
                            time.sleep(.1)
                        else:
                            output.seek(0)
                            self.fail("MCP did not become ready: " +
                                      output.read().decode("utf-8", "replace")[-3000:])
                        self.assertNotEqual(token, API_TOKEN)
                        self.assertEqual(stat.S_IMODE(token_file.stat().st_mode), 0o600)
                        self.assertIsNone(process.poll(), "Launcher unexpectedly stopped")
                        # Run a real subprocess against the active private gateway, using
                        # only the persisted token file (never passing it on the command line).
                        probe = subprocess.run(
                            [sys.executable, str(PREFLIGHT)],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=15,
                        )
                        self.assertEqual(probe.returncode, 0, probe.stderr)
                        report = json.loads(probe.stdout)
                        self.assertEqual(report["localMcpStatus"], "verified")
                        self.assertEqual(report["readOnlyToolCount"], 7)
                        self.assertEqual(report["chatgptExternalConnection"], "not_tested")
                        self.assertFalse(report["originalAgentExecutionVerified"])
                        self.assertNotIn(token, probe.stdout)
                        self.assertNotIn(API_TOKEN, probe.stdout)

                        # Client must fail closed with an incorrect token.
                        wrong_env = {**env, "DEBIAN13_MCP_GATEWAY_TOKEN":
                                     "deliberately-invalid-but-long-enough-token"}
                        rejected = subprocess.run(
                            [sys.executable, str(PREFLIGHT)], cwd=ROOT,
                            env=wrong_env, capture_output=True, text=True, timeout=8,
                        )
                        self.assertNotEqual(rejected.returncode, 0)
                        self.assertIn("BLOCKED", rejected.stderr)
                        self.assertNotIn(token, rejected.stderr)
                        self.assertNotIn(API_TOKEN, rejected.stderr)
                        # Browser requests or unauthorized external apps cannot read MCP tools.
                        unauthorized = urllib.request.Request(
                            "http://127.0.0.1:" + str(mcp_port) + "/mcp",
                            data=b'{"jsonrpc":"2.0","id":10,"method":"tools/list"}',
                            headers={"Content-Type": "application/json",
                                     "Accept": "application/json, text/event-stream"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as denied:
                            urllib.request.urlopen(unauthorized, timeout=2)
                        self.assertEqual(denied.exception.code, 401)
                        denied.exception.close()
                        return token
                    finally:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=6)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=3)

            first_token = run_and_probe()
            second_token = run_and_probe()
            self.assertEqual(first_token, second_token,
                             "Restart must preserve the private gateway token")


if __name__ == "__main__":
    unittest.main()
