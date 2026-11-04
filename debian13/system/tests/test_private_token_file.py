"""Credential-file safety regressions for Debian 13's launcher and MCP."""
from __future__ import annotations

import contextlib
import io
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SYSTEM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM))
import private_token_file as token_file


class PrivateTokenFileTests(unittest.TestCase):
    def test_generated_token_is_private_and_reused_after_restart(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "mcp-gateway-token"
            first = token_file.read_or_create(path)
            self.assertGreaterEqual(len(first), 32)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertFalse(path.is_symlink())
            self.assertEqual(first, token_file.read_or_create(path))

    def test_publicly_readable_token_is_blocked_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "operator-token"
            value = "deliberately-test-only-token-longer-than-32"
            path.write_text(value, encoding="ascii")
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private"):
                token_file.read_or_create(path)
            self.assertEqual(path.read_text(encoding="ascii"), value)
            path.chmod(0o600)
            self.assertEqual(token_file.read_or_create(path), value)

    def test_symlink_is_blocked_without_changing_target(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            target = base / "important-file"
            target.write_text("do not overwrite this value", encoding="ascii")
            path = base / "mcp-gateway-token"
            path.symlink_to(target)
            with self.assertRaises(ValueError):
                token_file.read_or_create(path)
            self.assertEqual(target.read_text(encoding="ascii"), "do not overwrite this value")

    def test_hard_link_and_owner_mismatch_are_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "operator-token"
            token_file.read_or_create(path)
            alias = Path(root) / "alias"
            os.link(path, alias)
            with self.assertRaisesRegex(ValueError, "private"):
                token_file.read_or_create(path)
            alias.unlink()
            with patch.object(token_file.os, "geteuid", return_value=os.geteuid() + 1):
                with self.assertRaisesRegex(ValueError, "private"):
                    token_file.read_or_create(path)

    def test_short_secret_and_directory_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "mcp-gateway-token"
            path.write_text("short", encoding="ascii")
            path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "invalid"):
                token_file.read_or_create(path)
            directory = Path(root) / "directory"
            directory.mkdir()
            with self.assertRaises(ValueError):
                token_file.read_or_create(directory)

    def test_cli_failure_never_prints_private_content(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "operator-token"
            secret = "private-test-token-that-must-not-be-revealed-123"
            path.write_text(secret, encoding="ascii")
            path.chmod(0o644)
            stdout, stderr = io.StringIO(), io.StringIO()
            with (contextlib.redirect_stdout(stdout),
                  contextlib.redirect_stderr(stderr)):
                code = token_file.main(["private_token_file.py", str(path)])
            self.assertEqual(code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("BLOCKED", stderr.getvalue())
            self.assertNotIn(secret, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
