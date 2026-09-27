import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from termux_agent.config import (
    EnvironmentFileError,
    Settings,
    load_env_file,
    parse_env_text,
    validate_base_url,
)


class ConfigTests(unittest.TestCase):
    def test_defaults_are_provider_neutral_and_localhost_only(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.base_url, "")
        self.assertEqual(settings.model, "")
        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.port, 8765)
        self.assertEqual(settings.api_key, "")

    def test_env_parser_preserves_quoted_special_characters_without_expansion(self):
        with tempfile.TemporaryDirectory() as folder:
            sentinel = Path(folder) / "executed"
            secret = "key $HOME; # 'quote' " + chr(92) + "= /"
            command_text = f"$(touch {sentinel})"
            lines = [
                "# local settings",
                f"AGENT_API_KEY={shlex.quote(secret)}",
                f"AGENT_ACCESS_TOKEN={shlex.quote(command_text)}",
                'AGENT_SYSTEM_PROMPT="hello $HOME # literal"',
                "AGENT_MODEL=literal#value",
            ]
            env_file = Path(folder) / ".env"
            env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            target = {"AGENT_API_KEY": "previous-environment-value"}
            parsed = load_env_file(env_file, target)
            self.assertEqual(parsed["AGENT_API_KEY"], secret)
            self.assertEqual(target["AGENT_ACCESS_TOKEN"], command_text)
            self.assertEqual(target["AGENT_SYSTEM_PROMPT"], "hello $HOME # literal")
            self.assertEqual(target["AGENT_MODEL"], "literal#value")
            self.assertFalse(sentinel.exists())

    def test_env_loader_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "elsewhere"
            target.write_text("AGENT_API_KEY=secret\\n", encoding="utf-8")
            link = Path(folder) / ".env"
            link.symlink_to(target)
            with self.assertRaises(EnvironmentFileError):
                load_env_file(link, {})

    def test_env_parser_rejects_malformed_or_non_agent_lines(self):
        for content in ("AGENT_API_KEY='unterminated", "PATH=/tmp"):
            with self.subTest(content=content), self.assertRaises(EnvironmentFileError):
                parse_env_text(content)

    def test_remote_api_keys_require_tls_but_local_http_is_allowed(self):
        validate_base_url("https://api.example.test/v1")
        validate_base_url("http://127.0.0.1:1234/v1")
        validate_base_url("http://[::1]:1234/v1")
        with self.assertRaises(ValueError):
            validate_base_url("http://192.168.1.8/v1")
        with self.assertRaises(ValueError):
            validate_base_url("https://user:password@example.test/v1")
        with self.assertRaises(ValueError):
            validate_base_url("https://example.test/v1?key=secret")

    def test_context_limit_is_normalized_to_complete_turn_pairs(self):
        with patch.dict(os.environ, {"AGENT_HISTORY_LIMIT": "3"}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.history_limit, 2)

    def test_provider_and_model_can_be_overridden(self):
        with patch.dict(os.environ, {
            "AGENT_BASE_URL": "https://example.test/v1/",
            "AGENT_MODEL": "sample-model",
        }, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.base_url, "https://example.test/v1")
        self.assertEqual(settings.model, "sample-model")


if __name__ == "__main__":
    unittest.main()
