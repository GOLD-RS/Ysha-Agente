import unittest

from termux_agent.server import CHAT_PAGE


class ChatPageTests(unittest.TestCase):
    def test_local_chat_page_is_present_and_self_contained(self):
        self.assertTrue(CHAT_PAGE.is_file())
        page = CHAT_PAGE.read_text(encoding="utf-8")
        self.assertIn("Ysha Agente", page)
        self.assertIn("/chat", page)
        self.assertIn("/sessions/", page)
        self.assertIn("AGENT_ACCESS_TOKEN", page)
        self.assertNotIn("https://fonts.googleapis.com", page)


if __name__ == "__main__":
    unittest.main()
