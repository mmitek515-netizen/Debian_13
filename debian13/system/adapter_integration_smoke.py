#!/usr/bin/env python3
"""Exercise PR #97's adapter against a running Debian system service."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit


EXPECTED_ADAPTER_SHA256 = "96d0269b6492a8da4275f63bde1f2727f77c0198ebf661a4aed9820ccec31db4"


def load_adapter(path: Path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED_ADAPTER_SHA256:
        raise RuntimeError("Adapter source does not match the reviewed PR #97 revision.")
    spec = importlib.util.spec_from_file_location("debian13_system_service_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the system-service adapter.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    adapter_type = getattr(module, "SystemServiceAdapter", None)
    if adapter_type is None:
        raise RuntimeError("Adapter module does not export SystemServiceAdapter.")
    return adapter_type


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", required=True, type=Path, help="Path to the pinned, reviewed PR #97 adapter")
    parser.add_argument(
        "--url",
        default=os.environ.get("DEBIAN13_SYSTEM_API_URL", "http://127.0.0.1:8080"),
        help="Loopback URL of the running Debian system service",
    )
    args = parser.parse_args()
    try:
        parsed = urlsplit(args.url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.port is None
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        adapter_type = load_adapter(args.adapter)
    except (OSError, ValueError, RuntimeError):
        print("BLOCKED: invalid loopback URL or unavailable adapter source.")
        return 1

    token = os.environ.get("DEBIAN13_API_TOKEN", "")
    adapter = adapter_type(args.url, token)
    if not adapter.configured:
        print("BLOCKED: valid service credentials are not configured.")
        return 1

    status = adapter.status()
    if status.get("status") not in {"provider_configured", "not_configured"}:
        print("FAIL: PR #97 adapter could not read profiles from the running service.")
        return 1
    if status.get("inference") != "not_verified":
        print("FAIL: adapter status unexpectedly claims verified inference.")
        return 1
    print(f"Adapter → running /v1/profiles: PASS ({status['status']}; inference not verified)")

    invalid_adapter = adapter_type(args.url, "invalid-integration-token-that-is-long-enough")
    invalid_status = invalid_adapter.status()
    if invalid_status.get("status") != "unavailable" or invalid_status.get("inference") != "not_verified":
        print("FAIL: invalid ****** not fail closed through the adapter.")
        return 1
    print("Adapter → invalid Bearer: PASS (unavailable; inference not verified)")

    if status.get("status") == "not_configured":
        try:
            adapter.chat("aria", "Readiness integration test; do not call a model.")
        except RuntimeError:
            print("Adapter → unconfigured /v1/chat: PASS (failed closed; no inference attempted)")
        else:
            print("FAIL: unconfigured chat unexpectedly returned content.")
            return 1
    else:
        print("Chat probe: SKIPPED (provider configured; avoiding an unapproved model request)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
