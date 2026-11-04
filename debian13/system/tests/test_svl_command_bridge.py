import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from svl_command_bridge import SVLCommandError, SVLCommandProcessor
from svl_kernel import SVLProtectedVariable


class SVLCommandTests(unittest.TestCase):
    def setUp(self):
        self.p = SVLCommandProcessor(
            diagnostics=lambda: {"service": "debian13-system"},
            integrations=lambda: {"mcp": "unverified"},
            agents=lambda: {"connected": False},
            tasks=lambda: {"workersRunning": 0},
        )

    def test_status_and_serialization(self):
        response = self.p.process("status")
        self.assertEqual(response["result"]["Compact_Metric_C"], 2.5)
        self.assertEqual(response["result"]["Performance"], "unverified")
        self.assertFalse(response["result"]["Agent_Execution_Verified"])
        self.assertNotIn("364_OMNIKLUCZ_ROOT", json.dumps(response))

    def test_topological_metric(self):
        self.assertEqual(self.p.process("metryka -inf inf")["result"]["metricC"], 2.5)
        self.assertEqual(self.p.process("metryka 0 0")["result"]["metricC"], 0.5)

    def test_readers(self):
        self.assertEqual(self.p.process("diagnostyka")["result"]["service"], "debian13-system")
        self.assertEqual(self.p.process("agenci")["result"], {"connected": False})
        self.assertEqual(self.p.process("zadania")["result"], {"workersRunning": 0})
        self.assertEqual(self.p.process("integracje")["result"]["mcp"], "unverified")

    def test_rejects_shell_and_invalid_inputs(self):
        for command in ("", "rm -rf /", "status; rm -rf /", "status extra", "metryka nan inf", "metryka x 5", "metryka 0", "x" * 201, "'broken"):
            with self.subTest(command=command), self.assertRaises(SVLCommandError):
                self.p.process(command)

    def test_denies_missing_hardcoded_root_token(self):
        variable = SVLProtectedVariable("TEST", "before")
        self.assertFalse(variable.update_protected_value("364_OMNIKLUCZ_ROOT", "after"))
        self.assertEqual(variable.value, "before")
        variable = SVLProtectedVariable("TEST", "before", update_token="test-only-secret")
        self.assertTrue(variable.update_protected_value("test-only-secret", "after"))
        self.assertEqual(variable.value, "after")


if __name__ == "__main__":
    unittest.main()
