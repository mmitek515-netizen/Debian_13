"""Offline regression checks for the opt-in Issue / PR agent proposal workflow."""
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "automation"))
import github_agent_proposal as agent


def proposed_patch(path="debian13/system/tests/test_example_agent.py"):
    return {
        "kind": "patch", "agent": "alex", "issue_number": 6,
        "summary": "Implement one tested improvement",
        "changes": [{"path": path, "content": "# safe test\n"}],
    }


class GitHubAgentProposalTests(unittest.TestCase):
    def test_paths_allow_small_debian_changes_only(self):
        for path in (
            "debian13/system/server.py",
            "debian13/system/tests/test_task.py",
            "debian13/ui/app.mjs",
            "debian13/ui/index.html",
            "debian13/ui/styles.css",
            "debian13/docs/STATUS.md",
            "debian13/README.md",
        ):
            with self.subTest(path=path):
                self.assertTrue(agent.allowed_path(path))
        for path in (
            ".github/workflows/evil.yml", "../../secrets.txt", "/etc/passwd",
            "debian13/system/.env", "debian13/system/../../.github/workflows/ci.yml",
            "debian13/compose.yaml", "debian13/system/Dockerfile",
            "debian13/system/setup.sh", "debian13/ui/private/token.env",
            "debian13/automation/github_agent_proposal.py",
            "debian13/system/secret\\escape.py",
        ):
            with self.subTest(path=path):
                self.assertFalse(agent.allowed_path(path))

    def test_accepts_valid_draft_issue_and_rejects_wrong_agent(self):
        item = {"kind": "issue", "agent": "aria", "title": "Improve diagnostics",
                "body": "Improve the existing status response and test HTTP error handling."}
        self.assertEqual(agent.validate(item)["agent"], "aria")
        with self.assertRaises(agent.ProposalError):
            agent.validate({**item, "agent": "invented"})

    def test_rejects_untrusted_changes(self):
        for bad in (
            {**proposed_patch(), "issue_number": True},
            {**proposed_patch(), "changes": []},
            {**proposed_patch(), "changes": [
                {"path": "debian13/system/server.py", "content": "hello"},
                {"path": "debian13/system/server.py", "content": "duplicate"},
            ]},
            proposed_patch(".github/workflows/debian13.yml"),
            {**proposed_patch(), "changes": [
                {"path": "debian13/system/server.py", "content": "x" * 18001}]},
        ):
            with self.subTest(data=str(bad)[:50]):
                with self.assertRaises(agent.ProposalError):
                    agent.validate(bad)

    def test_apply_writes_actual_file_and_never_follows_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent.apply(root, proposed_patch())
            target = root / "debian13/system/tests/test_example_agent.py"
            self.assertEqual(target.read_text(), "# safe test\n")
            target.unlink()
            outside = root / "outside.txt"
            outside.write_text("private", encoding="utf-8")
            target.symlink_to(outside)
            with self.assertRaises(agent.ProposalError):
                agent.apply(root, proposed_patch())
            self.assertEqual(outside.read_text(), "private")


    def test_workflow_title_prefix_selects_original_agents(self):
        """Exercise the actual regex embedded in the opt-in GitHub workflow."""
        workflow = (Path(__file__).resolve().parents[3] /
                    ".github/workflows/debian13-original-agents.yml")
        source = workflow.read_text(encoding="utf-8")
        found = re.search(r"m=re\.match\(r'([^']+)'", source)
        self.assertIsNotNone(found, "Agent prefix expression must exist.")
        pattern = re.compile(found.group(1))
        for name in agent.AGENTS:
            with self.subTest(name=name):
                match = pattern.match(f"[{name.title()}] fix Debian 13".lower())
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), name)
        self.assertIsNone(pattern.match("[unknown] something"))
        self.assertIsNone(pattern.match("This is an [Alex] task"))

    def test_https_model_is_required_and_redirects_are_blocked(self):
        self.assertEqual(agent.model_endpoint("https://example.net/v1/chat/completions"),
                         "https://example.net/v1/chat/completions")
        for candidate in (
            "http://ollama:11434/v1/chat/completions",
            "https://example.net/v1/chat/completions?key=secret",
            "https://example.net@attacker.io/v1/chat/completions",
            "https://example.net/unrelated",
            "",
        ):
            with self.subTest(candidate=candidate), self.assertRaises(agent.ProposalError):
                agent.model_endpoint(candidate)
        with self.assertRaises(agent.ProposalError):
            agent.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid")

    def test_local_ollama_is_permitted_only_with_explicit_trusted_runner_opt_in(self):
        url = "http://127.0.0.1:11434/v1/chat/completions"
        with patch.dict(os.environ, {"DEBIAN13_TRUSTED_LOCAL_MODEL": "1"}):
            self.assertEqual(agent.model_endpoint(url), url)
            with self.assertRaises(agent.ProposalError):
                agent.model_endpoint("http://evil.example:11434/v1/chat/completions")
            with self.assertRaises(agent.ProposalError):
                agent.model_endpoint("http://127.0.0.1:8080/v1/chat/completions")
        with patch.dict(os.environ, {"DEBIAN13_TRUSTED_LOCAL_MODEL": "0"}):
            with self.assertRaises(agent.ProposalError):
                agent.model_endpoint(url)

    def test_existing_model_provider_can_supply_real_patch_without_openai_dependency(self):
        response = {"choices": [{"message": {"content": json.dumps(proposed_patch())}}]}
        payload = json.dumps(response).encode()
        seen = []
        class MockOpener:
            def open(self, request, timeout):
                seen.append((request.full_url, request.data))
                return io.BytesIO(payload)
        with patch.dict(os.environ, {
            "DEBIAN13_MODEL_CHAT_URL": "https://example.net/v1/chat/completions",
            "DEBIAN13_MODEL_API_KEY": "inert-fake-token-for-test",
            "DEBIAN13_MODEL_NAME": "already-running-model",
        }), patch.object(agent.urllib.request, "build_opener", return_value=MockOpener()):
            with tempfile.TemporaryDirectory() as directory:
                actual = agent.create_proposal(Path(directory), "patch", "alex", {
                    "number": 6, "title": "Repair status", "body": "Fix the API."})
        self.assertEqual(actual["kind"], "patch")
        self.assertEqual(actual["issue_number"], 6)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "https://example.net/v1/chat/completions")
        self.assertIn(b"already-running-model", seen[0][1])
        self.assertNotIn(b"openai.com", seen[0][1])


if __name__ == "__main__":
    unittest.main()
