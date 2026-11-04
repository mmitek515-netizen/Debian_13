"""Offline tests: restarting the previous VM must not provision a new VM."""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "virtualization" / "resume-existing-vm.sh"


class ResumeExistingVmTests(unittest.TestCase):
    def run_helper(self, *args, env=None):
        e = os.environ.copy()
        if env:
            e.update(env)
        return subprocess.run(["bash", str(SCRIPT), *args], text=True, capture_output=True, env=e, timeout=10)

    def test_shell_syntax(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode, 0)

    def test_help(self):
        r = self.run_helper("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("WITHOUT rebuilding", r.stdout)

    def test_disallows_unknown_action(self):
        self.assertNotEqual(self.run_helper("--create").returncode, 0)

    def test_missing_original_container_fails_without_creating(self):
        with tempfile.TemporaryDirectory() as temp:
            self._fake_docker(temp, "missing")
            r = self.run_helper("--start", env=self._env(temp))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("not found", r.stderr)
            self.assertNotIn("start ", self._log(temp))

    def test_missing_disk_fails_without_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            self._fake_docker(temp, "available")
            r = self.run_helper("--start", env=self._env(temp))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("disk absent", r.stderr)
            self.assertNotIn("start ", self._log(temp))

    def test_read_only_check_keeps_container_stopped(self):
        with tempfile.TemporaryDirectory() as temp:
            self._fake_docker(temp, "available")
            self._make_images(temp)
            r = self.run_helper("--check", env=self._env(temp))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Read-only inspection complete", r.stdout)
            self.assertNotIn("start ", self._log(temp))

    def test_restart_only_calls_docker_start(self):
        with tempfile.TemporaryDirectory() as temp:
            self._fake_docker(temp, "available")
            self._make_images(temp)
            r = self.run_helper("--start", env=self._env(temp))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Start command submitted", r.stdout)
            self.assertEqual(self._log(temp).count("start vm_gemini_4"), 1)
            self.assertNotIn("up ", self._log(temp))

    def _env(self, temp):
        return {"PATH": f"{temp}:/usr/bin:/bin", "TEST_DOCKER_LOG": f"{temp}/commands.log",
                "TEST_VM_DATA": f"{temp}/data", "TEST_CONTAINER": Path(temp, "test-state.txt").read_text()}

    def _fake_docker(self, temp, state):
        Path(temp, "data").mkdir()
        docker = Path(temp, "docker")
        docker.write_text("""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$TEST_DOCKER_LOG"
case "$1" in
  info) exit 0 ;;
  container)
    [[ "$2" == inspect ]] || exit 1
    [[ "$TEST_CONTAINER" == available ]] || exit 1
    if [[ "$3" == --format ]]; then
      case "$4" in
        *Mounts*) printf '%s\\n' "$TEST_VM_DATA" ;;
        *State.Running*) printf 'false\\n' ;;
        *) exit 1 ;;
      esac
    fi
    exit 0 ;;
  start) [[ "$2" == vm_gemini_4 ]] ;;
  ps) printf 'vm_gemini_4 Up\\n' ;;
  *) exit 1 ;;
esac
""")
        docker.chmod(stat.S_IRWXU)
        Path(temp, "commands.log").write_text("")
        Path(temp, "test-state.txt").write_text(state)

    def _make_images(self, temp):
        for name in ["vm-gemini-4-restricted.qcow2", "debian-13-genericcloud-amd64.qcow2"]:
            (Path(temp, "data") / name).write_bytes(b"fake-test-data")

    def _log(self, temp):
        return Path(temp, "commands.log").read_text()


if __name__ == "__main__":
    unittest.main()
