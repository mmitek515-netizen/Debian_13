"""Safe, unprivileged contract checks for optional KVM host script."""
from pathlib import Path
import os
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "virtualization" / "kvm-vm.sh"


class KvmVmScriptTests(unittest.TestCase):
    def invoke(self, *args, extra_env=None):
        env = os.environ.copy()
        env.update(extra_env or {})
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            check=False,
            text=True,
            capture_output=True,
            env=env,
            timeout=10,
        )

    def test_shell_syntax(self):
        p = subprocess.run(["bash", "-n", str(SCRIPT)], check=False, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_help_is_non_destructive(self):
        p = self.invoke("--help")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("--create", p.stdout)
        self.assertIn("--check", p.stdout)

    def test_unknown_action_is_rejected(self):
        self.assertNotEqual(self.invoke("--delete").returncode, 0)

    def test_creation_without_verified_iso_is_rejected(self):
        p = self.invoke("--create", extra_env={"DEBIAN13_VM_ISO": "", "DEBIAN13_VM_ISO_SHA256": ""})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("DEBIAN13_VM_ISO", p.stderr)

    def test_invalid_vm_name_is_rejected(self):
        p = self.invoke("--check", extra_env={"DEBIAN13_VM_NAME": "unsafe;command"})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("Invalid VM name", p.stderr)


if __name__ == "__main__":
    unittest.main()
