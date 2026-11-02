"""Source identities for all four original owner agents; never claim fake inference."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from original_agents import report, ORIGINAL_AGENTS


class OriginalAgentsTests(unittest.TestCase):
    def test_original_profile_files_are_all_present(self):
        root = Path(__file__).resolve().parents[3]
        self.assertEqual(set(ORIGINAL_AGENTS), {"Alex", "Aria", "Astyria", "Aurelius"})
        for name in ORIGINAL_AGENTS:
            content = (root / ".github" / "agents" / f"{name}.agent.md").read_text()
            self.assertIn(f"name: {name}", content)
            self.assertIn("oryginaln", content.lower())

    def test_without_source_registry_all_original_workers_unverified(self):
        with patch.dict(os.environ, {
            "ALEX_EXISTING_API_URL": "", "BASTILLA_REMOTE_API_URL": ""
        }):
            data = report()
        self.assertFalse(data["registryConfigured"])
        self.assertFalse(data["registryReachable"])
        self.assertFalse(data["originalAgentExecutionVerified"])
        self.assertEqual(len(data["agents"]), 4)
        self.assertTrue(all(not agent["connected"] and not agent["workerVerified"]
                            for agent in data["agents"]))

    def test_registry_cannot_fake_live_workers(self):
        fixture = {"success": True, "tasks": [
            {"id": "a", "agent": "Alex", "status": "running"},
            {"id": "b", "agent": "Aria", "status": "completed"},
            {"id": "c", "agent": "Astyria", "status": "running"},
            {"id": "d", "agent": "Aurelius", "status": "queued"},
        ]}
        with patch("original_agents.existing_api_base", return_value="https://example.org/api"), \
             patch("original_agents.fetch_registry", return_value=fixture):
            result = report()
        self.assertTrue(result["registryReachable"])
        self.assertEqual([e["tasksInRegistry"] for e in result["agents"]], [1, 1, 1, 1])
        self.assertEqual([e["runningEntriesInRegistry"] for e in result["agents"]], [1, 0, 1, 0])
        self.assertTrue(all(e["workerVerified"] is False and e["connected"] is False
                            for e in result["agents"]))

    def test_remote_registry_error_not_exposed(self):
        with patch("original_agents.existing_api_base", return_value="https://private.example/api"), \
             patch("original_agents.fetch_registry", side_effect=Exception("SECRET VALUE")):
            report_data = report()
        self.assertFalse(report_data["registryReachable"])
        self.assertNotIn("SECRET", str(report_data))
        self.assertEqual(len(report_data["agents"]), 4)


if __name__ == "__main__":
    unittest.main()
