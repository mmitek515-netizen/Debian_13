"""Unit tests for Debian 13's explicit non-root systemd user-unit installer."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "install-user-service.py"
spec = importlib.util.spec_from_file_location("debian13_install_user_service", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class SystemdUserInstallerTests(unittest.TestCase):
    def test_render_has_private_mcp_and_no_root_or_public_bind(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "debian13"
            project.mkdir()
            (project / "start-local.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            content = installer.render_unit(project)
            self.assertIn("ExecStart=/usr/bin/bash " + str(project / "start-local.sh"), content)
            self.assertIn("Environment=DEBIAN13_ENABLE_MCP_HTTP=1", content)
            self.assertIn("NoNewPrivileges=yes", content)
            self.assertIn("WantedBy=default.target", content)
            self.assertIn("Restart=always", content)
            self.assertNotIn("User=root", content)
            self.assertNotIn("0.0.0.0", content)
            self.assertNotIn("Authorization", content)
            self.assertNotIn("DEBIAN13_API_TOKEN", content)
            self.assertNotIn("DEBIAN13_MCP_GATEWAY_TOKEN", content)
            self.assertNotIn("sudo", content)

    def test_atomic_install_is_idempotent_and_rejects_unreviewed_change(self):
        with tempfile.TemporaryDirectory() as td:
            unit = Path(td) / ".config/systemd/user/debian13-console.service"
            content = "[Unit]\nDescription=Test\n"
            self.assertEqual(installer.install_unit(unit, content), "installed")
            self.assertEqual(unit.read_text(encoding="utf-8"), content)
            self.assertEqual(stat.S_IMODE(unit.stat().st_mode), 0o600)
            self.assertEqual(installer.install_unit(unit, content), "unchanged")
            with self.assertRaisesRegex(ValueError, "review"):
                installer.install_unit(unit, content + "new")
            self.assertEqual(unit.read_text(encoding="utf-8"), content)
            self.assertEqual(installer.install_unit(unit, content + "new", force=True),
                             "installed")
            self.assertEqual(unit.read_text(encoding="utf-8"), content + "new")

    def test_install_refuses_symlink_target(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.write_text("unchanged", encoding="utf-8")
            link = Path(td) / ".config/systemd/user/debian13-console.service"
            link.parent.mkdir(parents=True)
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symbolic-link"):
                installer.install_unit(link, "changed", force=True)
            self.assertEqual(target.read_text(encoding="utf-8"), "unchanged")

    def test_render_refuses_unsafe_path_and_missing_launcher(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "Unsafe Path%here"
            project.mkdir()
            (project / "start-local.sh").write_text("#!/usr/bin/env bash\n")
            with self.assertRaisesRegex(ValueError, "without whitespace"):
                installer.render_unit(project)
            (project / "start-local.sh").unlink()
            with self.assertRaisesRegex(ValueError, "not found"):
                installer.render_unit(project)

    def test_check_is_no_write_and_rejects_root(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "debian13"
            project.mkdir()
            (project / "start-local.sh").write_text("#!/usr/bin/env bash\n")
            fake_home = Path(td) / "home"
            out, err = io.StringIO(), io.StringIO()
            with (patch.object(installer, "project_directory", return_value=project),
                  patch.object(installer.os, "geteuid", return_value=1000),
                  patch.object(Path, "home", return_value=fake_home),
                  contextlib.redirect_stdout(out), contextlib.redirect_stderr(err)):
                self.assertEqual(installer.main(["--check"]), 0)
            self.assertIn("not_installed", out.getvalue())
            self.assertFalse((fake_home / ".config/systemd").exists())
            with (patch.object(installer.os, "geteuid", return_value=0),
                  contextlib.redirect_stdout(io.StringIO()),
                  contextlib.redirect_stderr(err)):
                self.assertEqual(installer.main(["--install"]), 1)
            self.assertFalse((fake_home / ".config/systemd").exists())


if __name__ == "__main__":
    unittest.main()
