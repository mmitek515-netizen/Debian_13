#!/usr/bin/env python3
"""Live-container contract smoke: real HTTP, MCP stdio, and GPT Actions schema.

Run inside the running debian13-system container after Docker Compose startup.
No external AI provider, GPT account, or model download is assumed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HOST = "http://127.0.0.1:8080"
ROOT = Path("/opt/debian13/system")
TOKEN = os.environ.get("DEBIAN13_API_TOKEN", "")


def get(path: str, token: str | None) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(HOST + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def main() -> None:
    assert len(TOKEN) >= 32, "API token must be set in container"
    assert get("/healthz", None)[0] == 200
    assert get("/v1/integrations", None)[0] == 401
    status, data = get("/v1/integrations", TOKEN)
    assert status == 200
    assert {x["id"] for x in data["integrations"]} == {"mcp", "codex", "gpt_actions"}
    assert all(x["connected"] is False for x in data["integrations"])

    schema = json.loads((ROOT / "gpt-actions.openapi.json").read_text(encoding="utf-8"))
    assert schema["openapi"] == "3.0.3"
    assert schema["security"] == [{"bearerAuth": []}]
    for path in schema["paths"]:
        assert get(path, TOKEN)[0] == 200 if "get" in schema["paths"][path] else path == "/v1/chat"

    commands = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                    "clientInfo": {"name": "CI", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "debian13_profiles", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "debian13_integrations", "arguments": {}}},
    ]
    env = {**os.environ, "DEBIAN13_SYSTEM_API_URL": HOST}
    result = subprocess.run(
        [sys.executable, str(ROOT / "mcp_server.py")],
        input="".join(json.dumps(command) + "\n" for command in commands),
        text=True, capture_output=True, timeout=15, env=env, check=True,
    )
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert [response["id"] for response in responses] == [1, 2, 3, 4]
    assert "tools" in responses[1]["result"]
    profiles = json.loads(responses[2]["result"]["content"][0]["text"])
    assert {p["id"] for p in profiles["profiles"]} == {"aria", "astyria", "aurelius", "alex"}
    assert all(p["active"] is False for p in profiles["profiles"])
    assert responses[3]["result"]["isError"] is False
    print("PASS: real Debian 13 HTTP, bearer protection, MCP stdio and GPT Actions API contract")
    print("LIMIT: no remote GPT, Codex execution, autonomous workers or Ollama inference checked")


if __name__ == "__main__":
    main()
