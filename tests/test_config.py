import os
import unittest
from unittest.mock import patch

from termux_agent.config import Settings, validate_base_url


class ConfigTests(unittest.TestCase):
    def test_defaults_are_provider_neutral_and_localhost_only(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.base_url, "")
        self.assertEqual(settings.model, "")
        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.port, 8765)
        self.assertEqual(settings.api_key, "")

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
