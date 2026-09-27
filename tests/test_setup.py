import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from setup_termux import read_values, update_values  # noqa: E402


class SetupTests(unittest.TestCase):
    def test_secret_shell_quoting_round_trips_and_other_settings_survive(self):
        lines = [
            "# local configuration",
            "AGENT_API_KEY=",
            "AGENT_BASE_URL=https://apihub.agnes-ai.com/v1",
            "AGENT_MODEL=agnes-3.0-flash",
            'AGENT_SYSTEM_PROMPT="Keep this prompt intact."',
        ]
        secret = "abc$def'ghi/=="
        updated = update_values(lines, {
            "AGENT_API_KEY": secret,
            "AGENT_BASE_URL": "https://example.test/v1",
        })
        values = read_values(updated)
        self.assertEqual(values["AGENT_API_KEY"], secret)
        self.assertEqual(values["AGENT_BASE_URL"], "https://example.test/v1")
        self.assertEqual(values["AGENT_MODEL"], "agnes-3.0-flash")
        self.assertEqual(values["AGENT_SYSTEM_PROMPT"], "Keep this prompt intact.")
        self.assertIn("# local configuration", updated)


if __name__ == "__main__":
    unittest.main()
