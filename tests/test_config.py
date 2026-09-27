import os
import unittest
from unittest.mock import patch

from termux_agent.config import Settings


class ConfigTests(unittest.TestCase):
    def test_defaults_are_provider_neutral_and_localhost_only(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.base_url, "")
        self.assertEqual(settings.model, "")
        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.port, 8765)
        self.assertEqual(settings.api_key, "")

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
