#!/usr/bin/env python3
"""Generate an opt-in systemd user unit for the Debian 13 local console.

No root, no public ports, no systemctl execution, no tokens in unit content.
Use --check to preview readiness; --install writes only the user-owned unit.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

UNIT_NAME = "debian13-console.service"
SAFE_PATH = re.compile(r"^/[A-Za-z0-9_./-]+$")


def project_directory() -> Path:
    return Path(__file__).resolve().parent


def render_unit(project: Path) -> str:
    root = project.resolve(strict=True)
    launcher = root / "start-local.sh"
    if not launcher.is_file():
        raise ValueError("Debian 13 launcher not found.")
    # Values in systemd units interpret %, whitespace, and backslashes.
    # Reject ambiguous paths rather than risk unintended interpolation.
    if not SAFE_PATH.fullmatch(str(root)):
        raise ValueError("Install from a path without whitespace, percent signs or special characters.")
    if root == Path("/"):
        raise ValueError("Refusing root filesystem as project directory.")
    return (
        "[Unit]\n"
        "Description=Debian 13 Console (local GUI, API and read-only MCP)\n"
        "After=network.target\n"
        "StartLimitIntervalSec=120\n"
        "StartLimitBurst=6\n"
        "\n[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={root}\n"
        f"ExecStart=/usr/bin/bash {launcher}\n"
        "Environment=DEBIAN13_ENABLE_MCP_HTTP=1\n"
        "Environment=PYTHONDONTWRITEBYTECODE=1\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "TimeoutStopSec=20\n"
        "UMask=0077\n"
        "NoNewPrivileges=yes\n"
        "\n[Install]\n"
        "WantedBy=default.target\n"
    )


def install_unit(destination: Path, content: str, *, force: bool = False) -> str:
    """Atomically write one user-service file, refusing surprise overwrites."""
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError("Refusing to overwrite a symbolic-link unit.")
    if destination.exists():
        if not destination.is_file():
            raise ValueError("User service path must be a regular file.")
        existing = destination.read_text(encoding="utf-8")
        if existing == content:
            return "unchanged"
        if not force:
            raise ValueError("Unit differs; review it and use --force to replace it.")
    temp_path = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".debian13-unit-", dir=destination.parent)
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, destination)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return "installed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Debian 13 private systemd user-service installer")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Preview configuration without writes")
    group.add_argument("--install", action="store_true", help="Write user unit; does not start it")
    parser.add_argument("--force", action="store_true", help="Replace an existing different unit on --install")
    args = parser.parse_args(argv)
    if args.force and not args.install:
        parser.error("--force requires --install")
    if os.geteuid() == 0:
        print("BLOCKED: run this installer as a regular Debian user, never root.", file=sys.stderr)
        return 1
    try:
        unit = render_unit(project_directory())
        target = Path.home() / ".config/systemd/user" / UNIT_NAME
        if args.check:
            existing = target.read_text(encoding="utf-8") if target.is_file() else ""
            status = "matches" if existing == unit else ("different" if existing else "not_installed")
            print(f"PASS: safe user unit renderable; installation={status}")
            print(f"Target: {target}")
            print("No systemctl command was run; no permanent service started.")
        else:
            status = install_unit(target, unit, force=args.force)
            print(f"User unit {status}: {target}")
            print("Run: systemctl --user daemon-reload")
            print(f"Then: systemctl --user enable --now {UNIT_NAME}")
            print("Verify locally: python3 debian13/system/mcp_preflight.py")
            print("Codespaces can still be suspended. No root, external tunnel or autonomous AI is configured.")
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        # Avoid echoing configuration, tokens or file content.
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
