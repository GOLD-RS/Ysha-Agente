import os
import secrets
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
    validate_settings,
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
        self.assertEqual(settings.provider_max_attempts_per_response, 8)

    def test_env_parser_preserves_quoted_special_characters_without_expansion(self):
        with tempfile.TemporaryDirectory() as folder:
            sentinel = Path(folder) / "executed"
            parser_value = "literal $HOME; # 'quote' " + chr(92) + "= /"
            command_text = f"$(touch {sentinel})"
            lines = [
                "# local settings",
                f"AGENT_API_KEY={shlex.quote(parser_value)}",
                f"AGENT_ACCESS_TOKEN={shlex.quote(command_text)}",
                'AGENT_SYSTEM_PROMPT="hello $HOME # literal"',
                "AGENT_MODEL=literal#value",
            ]
            env_file = Path(folder) / ".env"
            env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            target = {"AGENT_API_KEY": "previous-parser-value"}
            parsed = load_env_file(env_file, target)
            self.assertEqual(parsed["AGENT_API_KEY"], parser_value)
            self.assertEqual(target["AGENT_ACCESS_TOKEN"], command_text)
            self.assertEqual(target["AGENT_SYSTEM_PROMPT"], "hello $HOME # literal")
            self.assertEqual(target["AGENT_MODEL"], "literal#value")
            self.assertFalse(sentinel.exists())

    def test_env_loader_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "elsewhere"
            target.write_text("AGENT_API_KEY=\\n", encoding="utf-8")
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

    def test_multiple_provider_profiles_select_model_and_order_fallbacks_from_env(self):
        environment = {
            "AGENT_PROVIDER_IDS": "primary,backup",
            "AGENT_PROVIDER_SELECTED": "backup",
            "AGENT_PROVIDER_FALLBACKS": "primary",
            "AGENT_PROVIDER_BACKUP_TYPE": "chat_completions",
            "AGENT_PROVIDER_BACKUP_API_KEY": "",
            "AGENT_PROVIDER_BACKUP_BASE_URL": "https://backup.example.test/v1",
            "AGENT_PROVIDER_BACKUP_MODEL": "backup-model",
            "AGENT_PROVIDER_BACKUP_TIMEOUT_SECONDS": "12.5",
            "AGENT_PROVIDER_BACKUP_MAX_RETRIES": "2",
            "AGENT_PROVIDER_PRIMARY_API_KEY": "",
            "AGENT_PROVIDER_PRIMARY_BASE_URL": "https://primary.example.test/v1",
            "AGENT_PROVIDER_PRIMARY_MODEL": "primary-model",
            "AGENT_PROVIDER_TOTAL_TIMEOUT_SECONDS": "60",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.selected_provider, "backup")
        self.assertEqual(settings.fallback_providers, ("primary",))
        self.assertEqual(settings.model, "backup-model")
        self.assertEqual(settings.provider_profiles[1].timeout_seconds, 12.5)
        self.assertEqual(settings.provider_profiles[1].max_retries, 2)
        self.assertEqual(settings.provider_total_timeout_seconds, 60)

    def test_provider_selection_and_fallback_must_reference_configured_ids(self):
        invalid = [
            {"AGENT_PROVIDER_IDS": "primary", "AGENT_PROVIDER_SELECTED": "missing"},
            {"AGENT_PROVIDER_IDS": "primary", "AGENT_PROVIDER_FALLBACKS": "missing"},
            {"AGENT_PROVIDER_IDS": "primary,primary"},
            {"AGENT_PROVIDER_IDS": "Primary"},
            {"AGENT_PROVIDER_IDS": "primary", "AGENT_PROVIDER_FALLBACKS": "primary"},
        ]
        for environment in invalid:
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(ValueError):
                    Settings.from_env()

    def test_provider_retry_and_total_timeout_configuration_is_bounded(self):
        for environment in (
            {"AGENT_PROVIDER_IDS": "primary", "AGENT_PROVIDER_PRIMARY_MAX_RETRIES": "3"},
            {"AGENT_PROVIDER_IDS": "primary", "AGENT_PROVIDER_PRIMARY_TIMEOUT_SECONDS": "0"},
            {"AGENT_PROVIDER_TOTAL_TIMEOUT_SECONDS": "NaN"},
            {"AGENT_PROVIDER_MAX_ATTEMPTS_PER_RESPONSE": "0"},
            {"AGENT_PROVIDER_MAX_ATTEMPTS_PER_RESPONSE": "25"},
        ):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(ValueError):
                    Settings.from_env()

    def test_validate_settings_checks_every_configured_provider(self):
        environment = {
            "AGENT_PROVIDER_IDS": "primary,backup",
            "AGENT_PROVIDER_PRIMARY_API_KEY": secrets.token_urlsafe(32),
            "AGENT_PROVIDER_PRIMARY_BASE_URL": "https://primary.example.test/v1",
            "AGENT_PROVIDER_PRIMARY_MODEL": "primary-model",
            "AGENT_PROVIDER_BACKUP_API_KEY": "",
            "AGENT_PROVIDER_BACKUP_BASE_URL": "https://backup.example.test/v1",
            "AGENT_PROVIDER_BACKUP_MODEL": "backup-model",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()
        with self.assertRaisesRegex(ValueError, "AGENT_PROVIDER_BACKUP_API_KEY"):
            validate_settings(settings)

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
