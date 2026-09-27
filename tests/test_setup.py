import stat
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from setup_termux import choose_provider, read_values, save_env, update_values  # noqa: E402


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

    def test_new_install_defaults_to_provider_neutral_endpoint(self):
        with patch("builtins.input", side_effect=["1", "https://api.example.test/v1", "custom-model"]):
            base_url, model = choose_provider({})
        self.assertEqual(base_url, "https://api.example.test/v1")
        self.assertEqual(model, "custom-model")

    def test_existing_env_gets_private_backup_and_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / ".env"
            env_file.write_text("AGENT_API_KEY=old-secret\n", encoding="utf-8")
            env_file.chmod(0o644)
            with patch("setup_termux.ENV_FILE", env_file):
                save_env(["AGENT_API_KEY=new-secret"])
            backup = Path(folder) / ".env.backup"
            self.assertEqual(backup.read_text(encoding="utf-8"), "AGENT_API_KEY=old-secret\n")
            self.assertEqual(env_file.read_text(encoding="utf-8"), "AGENT_API_KEY=new-secret\n")
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_env_symlink_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "private.txt"
            target.write_text("do-not-overwrite", encoding="utf-8")
            env_file = Path(folder) / ".env"
            env_file.symlink_to(target)
            with patch("setup_termux.ENV_FILE", env_file):
                with self.assertRaises(ValueError):
                    save_env(["AGENT_API_KEY=secret"])
            self.assertEqual(target.read_text(encoding="utf-8"), "do-not-overwrite")

    def test_current_provider_is_preserved_by_default(self):
        current = {"AGENT_BASE_URL": "https://provider.test/v1", "AGENT_MODEL": "chosen-model"}
        with patch("builtins.input", return_value=""):
            self.assertEqual(choose_provider(current), (current["AGENT_BASE_URL"], current["AGENT_MODEL"]))


if __name__ == "__main__":
    unittest.main()
