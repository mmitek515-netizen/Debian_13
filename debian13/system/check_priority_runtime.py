#!/usr/bin/env python3
"""Verify the private console, terminal and MCP; optionally probe local Ollama.

No remote URLs, GitHub writes, autonomous-agent claims or paid provider calls.
The optional chat probe creates four real chat sessions in the app's SQLite DB.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys

from mcp_launcher import get_token

MAX_REPLY = 1024 * 1024
AGENTS = ("alex", "aria", "astyria", "aurelius")


class CheckError(Exception):
    pass


def port_from_env(name: str, default: str) -> int:
    try:
        port = int(os.environ.get(name, default))
        if not 1 <= port <= 65535:
            raise ValueError
        return port
    except ValueError:
        raise CheckError(f"Invalid {name}.") from None


def request(port: int, method: str, path: str, *, payload=None, token=None,
            timeout=10) -> tuple[int, bytes]:
    headers = {}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json, text/event-stream"
    if token:
        headers["Authorization"] = "Bearer " + token
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        content = response.read(MAX_REPLY + 1)
        if len(content) > MAX_REPLY:
            raise CheckError("Local response exceeded the size limit.")
        return response.status, content
    except (OSError, TimeoutError, http.client.HTTPException):
        raise CheckError("A local service did not respond.") from None
    finally:
        connection.close()


def json_request(port: int, method: str, path: str, *, payload=None, token=None):
    status, content = request(port, method, path, payload=payload, token=token)
    if status != 200:
        raise CheckError(f"{path} returned HTTP {status}.")
    try:
        result = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        raise CheckError(f"{path} returned invalid JSON.") from None
    if not isinstance(result, dict):
        raise CheckError(f"{path} returned an unexpected response.")
    return result


def verify_core(ui_port: int, api_port: int, token: str) -> None:
    status, page = request(ui_port, "GET", "/")
    if status != 200 or b'id="chat-form"' not in page:
        raise CheckError("The console page or chat form is unavailable.")
    status_info = json_request(ui_port, "GET", "/api/v1/status")
    if status_info.get("application", {}).get("status") != "running":
        raise CheckError("The GUI proxy did not reach the running API.")
    print("PASS: GUI -> private API")

    terminal = json_request(ui_port, "POST", "/api/v1/terminal", payload={"command": "pwd"})
    if terminal.get("exitCode") != 0 or not terminal.get("output", "").strip():
        raise CheckError("The terminal did not return a successful pwd result.")
    print("PASS: terminal pwd through GUI proxy")

    def mcp(method, request_id=None, params=None):
        data = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if request_id is not None:
            data["id"] = request_id
        status, body = request(api_port, "POST", "/mcp", payload=data, token=token)
        if request_id is None:
            if status != 202 or body:
                raise CheckError("MCP notification was not accepted.")
            return {}
        if status != 200:
            raise CheckError(f"MCP returned HTTP {status}.")
        try:
            data = json.loads(body)
            if data.get("id") != request_id or not isinstance(data.get("result"), dict):
                raise ValueError
            return data["result"]
        except (ValueError, UnicodeDecodeError):
            raise CheckError("MCP returned an invalid JSON-RPC result.") from None

    initialized = mcp("initialize", 1, {"protocolVersion": "2025-11-25", "capabilities": {},
                                      "clientInfo": {"name": "priority-check", "version": "1"}})
    if initialized.get("protocolVersion") != "2025-11-25":
        raise CheckError("MCP protocol version was not negotiated.")
    mcp("notifications/initialized")
    tools = mcp("tools/list", 2).get("tools", [])
    if not any(isinstance(tool, dict) and tool.get("name") == "debian13_diagnostics" for tool in tools):
        raise CheckError("MCP diagnostic tool was not returned.")
    result = mcp("tools/call", 3, {"name": "debian13_diagnostics", "arguments": {}})
    if result.get("isError") is not False:
        raise CheckError("The MCP diagnostic call failed.")
    print("PASS: local authenticated MCP initialize, notification, tools/list and diagnostic call")


def verify_ollama_chat(ui_port: int) -> None:
    progress = json_request(ui_port, "GET", "/api/v1/integration-progress")
    modules = progress.get("modules", [])
    ollama = next((item for item in modules if item.get("id") == "ollama"), {})
    checks = ollama.get("checkpoints", [])
    if not any(item.get("id") == "private_model_endpoint_configured"
               and item.get("verified") is True for item in checks):
        raise CheckError("A private local Ollama endpoint is not configured; no model request was sent.")
    for agent in AGENTS:
        status, body = request(ui_port, "POST", "/api/v1/chat/stream",
                               payload={"agent": agent, "message": "Odpowiedz krótko: test połączenia."},
                               timeout=120)
        if status != 200:
            raise CheckError(f"Chat for {agent} returned HTTP {status}.")
        try:
            events = {}
            for block in body.decode("utf-8").replace("\r\n", "\n").split("\n\n"):
                fields = block.splitlines()
                name = next((line[7:] for line in fields if line.startswith("event: ")), None)
                data = next((line[6:] for line in fields if line.startswith("data: ")), None)
                if name and data:
                    events[name] = json.loads(data)
            if (not events.get("delta", {}).get("text", "").strip()
                    or events.get("done", {}).get("source") != "ollama"
                    or events["done"].get("agent") != agent
                    or not events["done"].get("model")):
                raise ValueError
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            raise CheckError(f"Chat for {agent} did not return a complete Ollama response.") from None
        print(f"PASS: {agent} chat profile received an Ollama reply (model: {events['done']['model']})", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama-chat", action="store_true",
                        help="send one local Ollama chat probe for each profile")
    args = parser.parse_args()
    try:
        ui_port = port_from_env("DEBIAN13_UI_PORT", "3000")
        api_port = port_from_env("DEBIAN13_API_PORT", "8765")
        verify_core(ui_port, api_port, get_token())
        if args.ollama_chat:
            verify_ollama_chat(ui_port)
        else:
            print("Ollama inference: NOT TESTED (use --ollama-chat).")
        print("Original agent workers, remote ChatGPT MCP and Issue-to-PR: NOT VERIFIED.")
        return 0
    except (CheckError, ValueError) as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
