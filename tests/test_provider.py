import os
import unittest
from unittest.mock import patch

from termux_agent.config import Settings
from termux_agent.provider import ChatProvider, ProviderError


class ProviderSecurityTests(unittest.TestCase):
    def test_refuses_plaintext_remote_endpoint_before_sending_api_key(self):
        environment = {
            "AGENT_API_KEY": "do-not-send",
            "AGENT_BASE_URL": "http://api.example.test/v1",
            "AGENT_MODEL": "test-model",
        }
        with patch.dict(os.environ, environment, clear=True):
            provider = ChatProvider(Settings.from_env())
        with patch("termux_agent.provider.urlopen") as open_url:
            with self.assertRaises(ProviderError) as caught:
                provider.complete([], [])
        open_url.assert_not_called()
        self.assertNotIn("do-not-send", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
