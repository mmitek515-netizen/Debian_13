#!/usr/bin/env python3
"""Exercise the built Debian service image through its loopback-published HTTP port."""

import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
import uuid


IMAGE = os.environ.get("DEBIAN13_IMAGE", "debian13-system:local")
TOKEN = secrets.token_urlsafe(48)
NAME = "debian13-smoke-" + uuid.uuid4().hex[:12]


def docker(*args: str, env: dict | None = None) -> str:
    return subprocess.run(
        ["docker", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def request_json(base_url: str, path: str, token: str | None = None, body: dict | None = None):
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url + path, data=data, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=3)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read()), response.headers


def main() -> None:
    env = os.environ.copy()
    env["DEBIAN13_API_TOKEN"] = TOKEN
    docker(
        "run",
        "--detach",
        "--rm",
        "--name",
        NAME,
        "--publish",
        "127.0.0.1::8080",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "--tmpfs",
        "/workspace:rw,noexec,nosuid,size=16m,uid=10001,gid=10001",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=512m",
        "--cpus=1",
        "--pids-limit=64",
        "--env",
        "DEBIAN13_API_TOKEN",
        IMAGE,
        env=env,
    )
    try:
        container = json.loads(docker("inspect", NAME))[0]
        host_config = container["HostConfig"]
        assert container["Config"]["User"] == "10001:10001"
        assert host_config["ReadonlyRootfs"] is True
        assert host_config["CapDrop"] == ["ALL"]
        assert any(
            option.split(":", 1)[0].lower() == "no-new-privileges"
            for option in host_config["SecurityOpt"]
        )
        assert host_config["Memory"] == 512 * 1024 * 1024
        assert host_config["PidsLimit"] == 64
        published_port = host_config["PortBindings"]["8080/tcp"][0]
        assert published_port["HostIp"] == "127.0.0.1"

        write_probe = subprocess.run(
            ["docker", "exec", "--user", "0", NAME, "/usr/bin/touch", "/etc/debian13-smoke-check"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert write_probe.returncode != 0
        assert "read-only file system" in write_probe.stderr.lower()

        port = docker("port", NAME, "8080/tcp").rsplit(":", 1)[1]
        base_url = f"http://127.0.0.1:{port}"
        for _ in range(40):
            try:
                status, health, _ = request_json(base_url, "/healthz")
                if status == 200 and health == {"status": "ok"}:
                    break
            except (OSError, ValueError):
                time.sleep(0.25)
        else:
            raise RuntimeError("Debian container did not become healthy.")

        status, _, _ = request_json(base_url, "/v1/profiles")
        assert status == 401, f"Unauthenticated profiles returned HTTP {status}."
        status, _, _ = request_json(
            base_url, "/v1/terminal", token="invalid-token", body={"command": "pwd"}
        )
        assert status == 401, f"Invalid bearer token returned HTTP {status}."
        status, _, _ = request_json(base_url, "/v1/diagnostics", token="invalid-token")
        assert status == 401, f"Invalid bearer token returned diagnostics HTTP {status}."

        status, profiles, _ = request_json(base_url, "/v1/profiles", TOKEN)
        assert status == 200 and len(profiles["profiles"]) == 4
        assert all(profile["active"] is False for profile in profiles["profiles"])

        status, diagnostics, _ = request_json(base_url, "/v1/diagnostics", TOKEN)
        assert status == 200
        assert diagnostics["service"] == "debian13-system"
        assert diagnostics["effectiveUid"] == 10001
        assert diagnostics["workspaceWritable"] is True
        assert diagnostics["providerConfigured"] is False
        assert diagnostics["linuxSecurity"].get("noNewPrivileges") is True

        status, terminal, _ = request_json(
            base_url, "/v1/terminal", TOKEN, {"command": "pwd"}
        )
        assert status == 200 and terminal["stdout"].strip() == "/workspace"

        status, identity, _ = request_json(
            base_url, "/v1/terminal", TOKEN, {"command": "id"}
        )
        assert status == 200 and "uid=10001" in identity["stdout"]

        status, unavailable, _ = request_json(
            base_url, "/v1/chat", TOKEN, {"profile": "aria", "message": "smoke test"}
        )
        assert status == 503 and unavailable["error"]["code"] == "provider_not_configured"

        limited = None
        for _ in range(32):
            status, _, headers = request_json(base_url, "/v1/profiles", TOKEN)
            if status == 429:
                limited = headers.get("Retry-After")
                break
            assert status == 200, f"Authenticated profiles returned HTTP {status}."
        assert limited and limited.isdigit(), "Rate limit did not return HTTP 429 with Retry-After."
        print(
            "PASS: isolated Debian container "
            f"{container['Image']} (uid=10001, read_only_rootfs, cap_drop=ALL, "
            "loopback_port, no_new_privileges); write denied; "
            "health, bearer auth, diagnostics, profiles, terminal, fail-closed chat, and rate limit."
        )
    finally:
        subprocess.run(["docker", "rm", "--force", NAME], check=False, capture_output=True)


if __name__ == "__main__":
    main()
