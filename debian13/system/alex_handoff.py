"""Capability-gated handoff to the OWNER'S ORIGINAL Alex API.

Fail closed unless the original remote service *explicitly* advertises the
Debian13 Issue-to-PR capability. Older /agent-tasks/run is NOT a programming
agent: its fallback writes an unrelated diagnostic artifact, so never call it.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from alex_bridge import NoRedirect, SOURCE_REPO, existing_api_base

TARGET_REPO = "mmitek515-netizen/Debian_13"
CAPABILITY = "debian13_issue_to_pr"
MAX_RESPONSE_BYTES = 16384


class AlexHandoffError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _token() -> str:
    token = os.getenv("ALEX_EXISTING_API_TOKEN", "")
    if (len(token) < 32 or len(token) > 512
            or any(ord(char) < 33 or ord(char) > 126 for char in token)):
        raise AlexHandoffError("missing_alex_token",
                                "Set ALEX_EXISTING_API_TOKEN in the server environment.")
    return token


def _invoke(method: str, path: str, payload: dict | None = None,
            idempotency_key: str = "") -> dict:
    base = existing_api_base()
    if not base:
        raise AlexHandoffError("alex_not_configured",
                               "Set ALEX_EXISTING_API_URL to the original Alex API.")
    token = _token()
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(data) > 8192:
            raise AlexHandoffError("request_too_large", "Alex task is too large.")
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=8) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if response.status not in ((200, 201, 202) if method == "POST" else (200,)):
                raise AlexHandoffError("alex_endpoint_unavailable",
                                       "Existing Alex endpoint returned an unexpected status.")
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 405, 501):
            raise AlexHandoffError("unsupported_capability",
                                    "Existing Alex does not offer the Debian 13 Issue-to-PR endpoint.") from exc
        raise AlexHandoffError("alex_endpoint_unavailable",
                                "Existing Alex API rejected the request.") from exc
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise AlexHandoffError("alex_offline", "Existing Alex API is not reachable.") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise AlexHandoffError("invalid_alex_response", "Existing Alex response is too large.")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AlexHandoffError("invalid_alex_response", "Existing Alex returned invalid JSON.") from exc
    if not isinstance(result, dict):
        raise AlexHandoffError("invalid_alex_response", "Existing Alex returned invalid data.")
    return result


def capabilities() -> dict:
    """Check real support. A task registry or Copilot profile alone is insufficient."""
    if not existing_api_base():
        return {"configured": False, "supported": False, "agentRuntimeVerified": False,
                "reason": "no_alex_endpoint"}
    if os.getenv("ALEX_ALLOW_TASK_DISPATCH") != "1":
        return {"configured": True, "supported": False, "agentRuntimeVerified": False,
                "reason": "dispatch_not_enabled"}
    result = _invoke("GET", "/agent-tasks/capabilities")
    supported = (
        result.get("sourceRepository") == SOURCE_REPO
        and result.get("agent") == "Alex"
        and result.get("protocolVersion") == 1
        and isinstance(result.get("capabilities"), list)
        and CAPABILITY in result["capabilities"]
    )
    return {
        "configured": True,
        "supported": supported,
        "agentRuntimeVerified": False,
        "reason": "supported_protocol_advertised" if supported else "capability_missing",
    }


def submit_task(task: dict) -> dict:
    """Send only an operator-requested, review-only PR task to original Alex."""
    if task.get("agent") != "alex" or task.get("status") != "queued":
        raise AlexHandoffError("invalid_task", "Only queued Alex tasks may be dispatched.")
    if task.get("execution") != "not_started":
        raise AlexHandoffError("task_already_executed", "Task is not in a dispatchable state.")
    if os.getenv("ALEX_ALLOW_TASK_DISPATCH") != "1":
        raise AlexHandoffError("dispatch_not_enabled", "Operator must opt into Alex dispatch.")
    state = capabilities()
    if not state["supported"]:
        raise AlexHandoffError("unsupported_capability",
                               "Existing Alex has not advertised Debian 13 Issue-to-PR support.")
    payload = {
        "agent": "Alex",
        "capability": CAPABILITY,
        "task": {
            "id": task["id"],
            "title": task["title"],
            "description": task["description"],
            "kind": task["kind"],
            "targetRepository": TARGET_REPO,
        },
        "mode": "pull_request_proposal",
        "purchaseAuthorized": False,
        "autoMerge": False,
    }
    result = _invoke("POST", "/agent-tasks/submit", payload, idempotency_key=task["id"])
    remote_id = result.get("taskId")
    if (result.get("accepted") is not True
            or result.get("agent") != "Alex"
            or result.get("capability") != CAPABILITY
            or not isinstance(remote_id, str) or not 1 <= len(remote_id) <= 128):
        raise AlexHandoffError("submission_unverified",
                               "Existing Alex did not confirm accepting the task.")
    return {
        "acceptedByRemoteApi": True,
        "remoteTaskId": remote_id,
        "agentExecutionVerified": False,
        "pullRequestVerified": False,
        "purchaseAuthorized": False,
    }
