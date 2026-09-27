import unittest

from termux_agent.agent import Agent


class FakeProvider:
    def complete(self, message):
        return f"eco: {message}"


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.agent = Agent(FakeProvider())

    def test_responds_with_trimmed_message(self):
        self.assertEqual(self.agent.respond("  oi  "), "eco: oi")

    def test_rejects_empty_message(self):
        with self.assertRaises(ValueError):
            self.agent.respond("   ")

    def test_rejects_oversized_message(self):
        with self.assertRaises(ValueError):
            self.agent.respond("x" * 12_001)


if __name__ == "__main__":
    unittest.main()
