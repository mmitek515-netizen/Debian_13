"""Read-only adapter to the ORIGINAL owner's Alex agent registry in AI Studio.

The original service lives in u6930438163-code/AI_Studio_BastillaOS and
exposes GET /api/agent-tasks. This adapter does not clone or simulate Alex,
issue commands, or assert that a task implies active model inference.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

SOURCE_REPO = "u6930438163-code/AI_Studio_BastillaOS"
MAX_BYTES = 262_144
MAX_VISIBLE = 50
ALLOWED_STATES = frozenset({"queued", "running", "completed", "failed", "cancelled"})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def existing_api_base() -> str | None:
    """Only an explicitly configured HTTPS source or local loopback is trusted."""
    raw = (os.getenv("ALEX_EXISTING_API_URL")
           or os.getenv("BASTILLA_REMOTE_API_URL") or "").strip().rstrip("/")
    if not raw:
        return None
    parsed = urllib.parse.urlsplit(raw)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != "/api"):
        raise ValueError("Existing Alex API must be an HTTPS URL ending in /api")
    if parsed.scheme == "http" and parsed.hostname not in (
            "localhost", "127.0.0.1", "::1"):
        raise ValueError("Remote Alex API must use HTTPS")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid Alex API port")
    return raw


def fetch_registry() -> dict:
    base = existing_api_base()
    if not base:
        raise ValueError("Existing Alex API is not configured")
    token = os.getenv("ALEX_EXISTING_API_TOKEN", "").strip()
    if token and (len(token) > 512 or any(ord(ch) < 33 or ord(ch) > 126 for ch in token)):
        raise ValueError("Invalid Alex API token")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(base + "/agent-tasks", headers=headers, method="GET")
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(request, timeout=8) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Existing Alex API response is too large")
    data = json.loads(raw)
    if (not isinstance(data, dict) or data.get("success") is not True
            or not isinstance(data.get("tasks"), list)):
        raise ValueError("Existing Alex API returned an invalid task registry")
    return data


def visible_alex_tasks(data: dict) -> list[dict]:
    """Do not expose other agents' tasks, internal logs or artifact file contents."""
    filtered = []
    for item in data["tasks"]:
        if not isinstance(item, dict) or item.get("agent") != "Alex":
            continue
        status = item.get("status")
        if status not in ALLOWED_STATES:
            continue
        filtered.append({
            "id": str(item.get("id", ""))[:128],
            "title": str(item.get("title", ""))[:200],
            "status": status,
            "createdAt": str(item.get("createdAt", ""))[:40],
            "completedAt": str(item.get("completedAt", ""))[:40] or None,
            "artifactRecorded": isinstance(item.get("artifact"), dict),
        })
        if len(filtered) >= MAX_VISIBLE:
            break
    return filtered


def read_existing_alex(tool_name: str) -> dict:
    """MCP-safe read actions. No task creation, execution, or purchases."""
    if tool_name not in {"alex_existing_status", "alex_existing_tasks"}:
        raise ValueError("Unknown Alex tool")
    if existing_api_base() is None:
        return {
            "sourceRepository": SOURCE_REPO,
            "configured": False,
            "registryReachable": False,
            "alexWorkerVerified": False,
            "message": "Set ALEX_EXISTING_API_URL in the runtime; no external Alex endpoint checked.",
        }
    data = fetch_registry()
    tasks = visible_alex_tasks(data)
    common = {
        "sourceRepository": SOURCE_REPO,
        "configured": True,
        "registryReachable": True,
        "alexWorkerVerified": False,
        "meaning": "Task registry data only; no proof that an autonomous Alex LLM is running.",
    }
    if tool_name == "alex_existing_status":
        common["alexTasksInReturnedPage"] = len(tasks)
        common["reportedRunningTasks"] = sum(t["status"] == "running" for t in tasks)
    else:
        common["tasks"] = tasks
    return common
