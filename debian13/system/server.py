#!/usr/bin/env python3
"""Small authenticated API for the standalone Debian 13 system prototype."""

from __future__ import annotations

import base64
import binascii
import hmac
import http.server
import json
import os
import platform
import selectors
import shlex
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

MAX_BODY_BYTES = 16 * 1024
MAX_VISION_BODY_BYTES = 3 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_MESSAGE_CHARS = 4000
MAX_COMMAND_CHARS = 2000
COMMAND_TIMEOUT_SECONDS = 10
CHAT_TIMEOUT_SECONDS = 45
RATE_WINDOW_SECONDS = 60
RATE_LIMIT = 30

PROFILES = {
    "aria": {
        "name": "Aria",
        "role": "Integracja modeli AI i transport",
        "prompt": "You are Aria, responsible for AI model integration and transport. Be clear about uncertainty.",
    },
    "astyria": {
        "name": "Astyria",
        "role": "Interfejs, dostępność i wygoda obsługi",
        "prompt": "You are Astyria, responsible for interface usability and accessibility. Be clear about uncertainty.",
    },
    "aurelius": {
        "name": "Aurelius",
        "role": "Bezpieczeństwo, prywatność i testy",
        "prompt": "You are Aurelius, responsible for security, privacy, and testing. Be clear about uncertainty.",
    },
    "alex": {
        "name": "Alex",
        "role": "Architektura i integracja systemu",
        "prompt": "You are Alex, responsible for system architecture and integration. Be clear about uncertainty.",
    },
}

COMMANDS = {
    "pwd": "/usr/bin/pwd",
    "ls": "/usr/bin/ls",
    "cat": "/usr/bin/cat",
    "head": "/usr/bin/head",
    "tail": "/usr/bin/tail",
    "wc": "/usr/bin/wc",
    "grep": "/usr/bin/grep",
    "date": "/usr/bin/date",
    "whoami": "/usr/bin/whoami",
    "id": "/usr/bin/id",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_provider_url(value: str) -> str:
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme == "https":
        allowed = True
    elif parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        allowed = True
    elif parsed.scheme == "http" and parsed.hostname == "ollama" and os.environ.get("DEBIAN13_ALLOW_INTERNAL_OLLAMA") == "1" and parsed.port == 11434:
        allowed = True
    else:
        allowed = False
    if (
        not allowed
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.rstrip("/").endswith("/v1/chat/completions")
    ):
        raise ValueError("MODEL_CHAT_URL must be an HTTPS chat-completions URL (HTTP is allowed for loopback tests).")
    return value


def safe_workspace_path(workspace: Path, raw_path: str) -> str:
    if not raw_path or raw_path.startswith("-"):
        raise ApiError(400, "invalid_path", "File arguments must be relative workspace paths.")
    candidate = (workspace / raw_path).resolve()
    try:
        relative = candidate.relative_to(workspace)
    except ValueError as exc:
        raise ApiError(403, "path_outside_workspace", "Path is outside the terminal workspace.") from exc
    return str(relative) if str(relative) != "." else "."


def command_argv(command: str, workspace: Path) -> list[str]:
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND_CHARS:
        raise ApiError(400, "invalid_command", "Supply a command of 1–2000 characters.")
    try:
        parts = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ApiError(400, "invalid_command", "Command quoting is invalid.") from exc
    if not parts or parts[0] not in COMMANDS:
        raise ApiError(403, "command_not_allowed", "This terminal command is not in the allowed command list.")

    name, args = parts[0], parts[1:]
    if name in {"pwd", "date", "whoami", "id"}:
        if args:
            raise ApiError(400, "invalid_arguments", f"{name} does not accept arguments.")
        return [COMMANDS[name]]

    if name == "grep":
        if len(args) < 2 or args[0].startswith("-") or len(args[0]) > 200:
            raise ApiError(400, "invalid_arguments", "Use grep PATTERN WORKSPACE_FILE [...].")
        files = [safe_workspace_path(workspace, path) for path in args[1:]]
        return [COMMANDS[name], "--", args[0], *files]

    if name in {"head", "tail"}:
        count = "10"
        if args and args[0] == "-n":
            if (
                len(args) < 3
                or not args[1].isdigit()
                or len(args[1]) > 3
                or not 1 <= int(args[1]) <= 200
            ):
                raise ApiError(400, "invalid_arguments", f"Use {name} [-n 1..200] WORKSPACE_FILE [...].")
            count, args = args[1], args[2:]
        if not args:
            raise ApiError(400, "invalid_arguments", f"{name} requires a workspace file.")
        files = [safe_workspace_path(workspace, path) for path in args]
        return [COMMANDS[name], "-n", count, "--", *files]

    if name == "ls":
        paths = [safe_workspace_path(workspace, path) for path in args] if args else ["."]
        return [COMMANDS[name], "--", *paths]

    if name in {"cat", "wc"}:
        paths = [safe_workspace_path(workspace, path) for path in args] if args else []
        return [COMMANDS[name], "--", *paths]

    raise ApiError(403, "command_not_allowed", "This terminal command is not in the allowed command list.")


def run_terminal(command: str, workspace: Path) -> dict:
    argv = command_argv(command, workspace)
    try:
        process = subprocess.Popen(
            argv,
            cwd=workspace,
            env={"HOME": str(workspace), "LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        raise ApiError(500, "command_start_failed", "The terminal command could not be started.") from exc

    selector = selectors.DefaultSelector()
    output = {"stdout": bytearray(), "stderr": bytearray()}
    for stream, key in ((process.stdout, "stdout"), (process.stderr, "stderr")):
        selector.register(stream, selectors.EVENT_READ, key)
    deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS
    total = 0
    try:
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise ApiError(504, "command_timeout", "The terminal command exceeded its time limit.")
            for key, _ in selector.select(min(remaining, 0.2)):
                chunk = os.read(key.fileobj.fileno(), min(65536, MAX_OUTPUT_BYTES + 1 - total))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > MAX_OUTPUT_BYTES:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    raise ApiError(413, "output_too_large", "Terminal output exceeded the 1 MiB limit.")
                output[key.data].extend(chunk)
        code = process.wait()
    finally:
        selector.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()
    return {
        "exitCode": code,
        "stdout": output["stdout"].decode("utf-8", errors="replace"),
        "stderr": output["stderr"].decode("utf-8", errors="replace"),
    }


def validate_image(image: object) -> str:
    """Validate PNG/JPEG base64 and return a bounded data URI for the model."""
    if not isinstance(image, dict) or set(image) != {"mime_type", "base64"}:
        raise ApiError(400, "invalid_image", "Expected an image with mime_type and base64.")
    mime = image.get("mime_type")
    encoded = image.get("base64")
    if mime not in ("image/png", "image/jpeg") or not isinstance(encoded, str):
        raise ApiError(400, "invalid_image", "Only PNG and JPEG images are supported.")
    if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ApiError(413, "image_too_large", "Image exceeds 2 MiB.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError(400, "invalid_image", "Invalid base64-encoded image.") from exc
    if len(raw) > MAX_IMAGE_BYTES or not raw:
        raise ApiError(413, "image_too_large", "Image exceeds 2 MiB or is empty.")
    if mime == "image/png":
        correct = raw.startswith(b"\x89PNG\r\n\x1a\n")
    else:
        correct = raw.startswith(b"\xff\xd8\xff")
    if not correct:
        raise ApiError(400, "invalid_image", "Image bytes do not match the declared MIME type.")
    return "data:" + mime + ";base64," + encoded


def complete_chat(profile: str, message: str, config: dict, image: str | None = None) -> tuple[str, str]:
    if not config["model_chat_url"] or not config["model_api_key"] or not config["model_name"]:
        raise ApiError(503, "provider_not_configured", "No AI model provider is configured.")
    model = config.get("vision_model_name", "") if image is not None else config["model_name"]
    if not model:
        raise ApiError(503, "vision_not_configured", "A vision model is not configured.")
    user_content = message if image is None else [
        {"type": "text", "text": message},
        {"type": "image_url", "image_url": {"url": image}},
    ]
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": PROFILES[profile]["prompt"]},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
    }).encode("utf-8")
    request = urllib.request.Request(
        config["model_chat_url"],
        data=payload,
        headers={
            "Authorization": "Bearer " + config["model_api_key"],
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(NoRedirectHandler())
    try:
        with opener.open(request, timeout=CHAT_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise ApiError(502, "provider_error", "The configured model provider returned an error.")
            raw = response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ApiError(502, "provider_error", "The configured model provider returned an error.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiError(504, "provider_unavailable", "The configured model provider did not respond.") from exc
    if len(raw) > MAX_BODY_BYTES:
        raise ApiError(502, "provider_response_too_large", "The model provider response exceeded the size limit.")
    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ApiError(502, "invalid_provider_response", "The model provider returned an invalid response.") from exc
    if not isinstance(content, str) or not content.strip():
        raise ApiError(502, "empty_provider_response", "The model provider returned no message.")
    return content.strip()[:MAX_MESSAGE_CHARS], model


def runtime_diagnostics(server) -> dict:
    linux_security = {}
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        for line in status.splitlines():
            name, separator, value = line.partition(":")
            if not separator:
                continue
            if name == "NoNewPrivs":
                linux_security["noNewPrivileges"] = value.strip() == "1"
            elif name == "Seccomp":
                linux_security["seccompMode"] = int(value.strip())
            elif name == "CapEff":
                linux_security["effectiveCapabilities"] = value.strip()
    except (OSError, ValueError):
        pass

    return {
        "service": "debian13-system",
        "pythonVersion": platform.python_version(),
        "effectiveUid": os.geteuid(),
        "effectiveGid": os.getegid(),
        "workspaceWritable": os.access(server.workspace, os.W_OK),
        "providerConfigured": bool(
            server.config["model_chat_url"]
            and server.config["model_api_key"]
            and server.config["model_name"]
        ),
        "linuxSecurity": linux_security,
    }


class Debian13Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, address: tuple[str, int], config: dict):
        self.config = config
        self.workspace = Path(config["workspace"]).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._rates: dict[str, tuple[float, int]] = {}
        self._rates_lock = threading.Lock()
        super().__init__(address, SystemHandler)


class SystemHandler(http.server.BaseHTTPRequestHandler):
    server: Debian13Server
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        # Never log request bodies, authorization headers, or model credentials.
        super().log_message("%s %s", self.address_string(), self.path.split("?", 1)[0])

    def _send_json(self, status: int, data: dict, headers: dict | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_chat_events(self, content: str, profile: str, model: str) -> None:
        # A provider response is delivered as a single event after completion.
        # This is NOT token-by-token model streaming and is not persisted.
        source = "ollama" if urllib.parse.urlsplit(
            self.server.config["model_chat_url"]
        ).hostname == "ollama" else "model_provider"
        frames = [
            ("meta", {"model": model, "session_persisted": False}),
            ("delta", {"text": content}),
            ("done", {"agent": profile, "source": source, "model": model}),
        ]
        body = "".join(
            "event: " + event + "\n" +
            "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            for event, payload in frames
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _authorize(self) -> bool:
        expected = "Bearer " + self.server.config["api_token"]
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            self._send_json(401, {"error": {
                "code": "unauthorized",
                "message": "A valid bearer token is required.",
                "requestId": str(uuid.uuid4()),
            }})
            return False
        return True

    def _allow_request(self) -> bool:
        now = time.monotonic()
        address = self.client_address[0]
        with self.server._rates_lock:
            start, count = self.server._rates.get(address, (now, 0))
            if now - start >= RATE_WINDOW_SECONDS:
                start, count = now, 0
            if count >= self.server.config.get("rate_limit", RATE_LIMIT):
                retry = max(1, int(RATE_WINDOW_SECONDS - (now - start)))
                self._send_json(
                    429,
                    {"error": {
                        "code": "rate_limited",
                        "message": "Request rate limit exceeded.",
                        "requestId": str(uuid.uuid4()),
                    }},
                    {"Retry-After": str(retry)},
                )
                return False
            self.server._rates[address] = (start, count + 1)
            if len(self.server._rates) > 1024:
                self.server._rates = {
                    key: value for key, value in self.server._rates.items()
                    if now - value[0] < RATE_WINDOW_SECONDS
                }
        return True

    def _read_json(self, limit: int = MAX_BODY_BYTES) -> dict:
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdigit():
            raise ApiError(400, "invalid_content_length", "A valid Content-Length header is required.")
        if len(raw_length) > 8:
            raise ApiError(413, "request_too_large", "Request body exceeds 16 KiB.")
        length = int(raw_length)
        if length > limit:
            raise ApiError(413, "request_too_large", "Request body exceeds the size limit.")
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ApiError(400, "invalid_json", "Request body must be valid JSON.") from exc
        if not isinstance(data, dict):
            raise ApiError(400, "invalid_json", "Request body must be a JSON object.")
        return data

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return
        if not self._allow_request():
            return
        if not self._authorize():
            return
        if self.path == "/v1/profiles":
            self._send_json(200, {
                "profiles": [
                    {"id": key, "name": value["name"], "role": value["role"], "active": False}
                    for key, value in PROFILES.items()
                ],
                "providerConfigured": bool(
                    self.server.config["model_chat_url"]
                    and self.server.config["model_api_key"]
                    and self.server.config["model_name"]
                ),
            })
            return
        if self.path == "/v1/diagnostics":
            self._send_json(200, runtime_diagnostics(self.server))
            return
        if self.path == "/v1/integrations":
            self._send_json(200, {"integrations": [
                {"id": "mcp", "name": "MCP", "status": "stdio_available",
                 "connected": False, "description": "Read-only MCP stdio bridge; client connection not verified."},
                {"id": "gpt_actions", "name": "GPT Actions", "status": "schema_available",
                 "connected": False, "description": "OpenAPI document available; HTTPS deployment and GPT setup required."},
                {"id": "codex", "name": "Codex", "status": "workflow_available",
                 "connected": False, "description": "GitHub Actions workflow; requires OPENAI_API_KEY and a verified run."},
            ]})
            return
        if self.path == "/api/v1/status":
            report = runtime_diagnostics(self.server)
            self._send_json(200, {
                "application": {"status": "running", "product": "Debian 13 Console"},
                "operating_system": {"runtime": {
                    "distribution": platform.platform(),
                    "debian_13_boot_verified": False,
                }},
                "model": {
                    "status": "configured" if report["providerConfigured"] else "not_configured",
                    "inference": "unverified",
                },
                "task_state": "Brak uruchomionych workerów",
            })
            return
        if self.path == "/api/v1/agents":
            self._send_json(200, {"agents": [
                {"id": key, "name": profile["name"], "role": profile["role"],
                 "status": "profile_configured", "worker": "not_running"}
                for key, profile in PROFILES.items()
            ]})
            return
        if self.path == "/api/v1/tasks":
            self._send_json(200, {"tasks": []})
            return
        if self.path == "/api/v1/events":
            self._send_json(200, {"events": []})
            return
        self._send_json(404, {"error": {"code": "not_found", "requestId": str(uuid.uuid4())}})

    def do_POST(self) -> None:
        if not self._allow_request():
            return
        if not self._authorize():
            return
        request_id = str(uuid.uuid4())
        try:
            data = self._read_json(MAX_VISION_BODY_BYTES if self.path == "/v1/vision" else MAX_BODY_BYTES)
            if self.path in ("/v1/terminal", "/api/v1/terminal"):
                result = run_terminal(data.get("command"), self.server.workspace)
                if self.path == "/api/v1/terminal":
                    self._send_json(200, {"requestId": request_id, "output": result["stdout"] + result["stderr"],
                                          "exitCode": result["exitCode"]})
                else:
                    self._send_json(200, {"requestId": request_id, **result})
                return
            if self.path in ("/v1/chat", "/v1/vision", "/api/v1/chat/stream"):
                profile = data.get("agent") if self.path == "/api/v1/chat/stream" else data.get("profile")
                message = data.get("message")
                if not isinstance(profile, str) or profile not in PROFILES:
                    raise ApiError(400, "invalid_profile", "Select aria, astyria, aurelius, or alex.")
                if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE_CHARS:
                    raise ApiError(400, "invalid_message", "Message must contain 1–4000 characters.")
                image = validate_image(data.get("image")) if self.path == "/v1/vision" else None
                content, model = complete_chat(profile, message.strip(), self.server.config, image)
                if self.path == "/api/v1/chat/stream":
                    self._send_chat_events(content, profile, model)
                    return
                self._send_json(200, {
                    "requestId": request_id,
                    "profile": profile,
                    "content": content,
                    "model": model,
                })
                return
            self._send_json(404, {"error": {"code": "not_found", "requestId": request_id}})
        except ApiError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": str(exc), "requestId": request_id}})
        except (BrokenPipeError, ConnectionResetError):
            return


def load_config() -> dict:
    token = os.environ.get("DEBIAN13_API_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("DEBIAN13_API_TOKEN must contain at least 32 characters.")
    try:
        provider_url = validate_provider_url(os.environ.get("MODEL_CHAT_URL", "").strip())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return {
        "api_token": token,
        "model_chat_url": provider_url,
        "model_api_key": os.environ.get("MODEL_API_KEY", ""),
        "model_name": os.environ.get("MODEL_NAME", ""),
        "vision_model_name": os.environ.get("VISION_MODEL_NAME", ""),
        "workspace": os.environ.get("WORKSPACE_DIR", "/workspace"),
        "host": os.environ.get("HOST", "127.0.0.1"),
        "port": int(os.environ.get("PORT", "8080")),
    }


def main() -> None:
    config = load_config()
    server = Debian13Server((config["host"], config["port"]), config)
    print(f"Debian 13 system API listening on {config['host']}:{config['port']}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
