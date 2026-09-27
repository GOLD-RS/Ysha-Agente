import tempfile
import unittest

from termux_agent.agent import Agent
from termux_agent.history import HistoryStore
from termux_agent.tools import ToolError, calculate
from termux_agent.server import authorization_valid


class FakeProvider:
    def __init__(self, messages=None):
        self.settings = type("Settings", (), {"system_prompt": "You are a test agent"})()
        self.messages = list(messages or [{"content": "eco de teste", "tool_calls": []}])
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(messages)
        return self.messages.pop(0)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.history = HistoryStore(f"{self.temp.name}/memory.sqlite3", limit=6)
        self.provider = FakeProvider()
        self.agent = Agent(self.provider, self.history)

    def tearDown(self):
        self.temp.cleanup()

    def test_saves_conversation_and_reuses_context(self):
        self.assertEqual(self.agent.respond("sessao1", "  oi  "), "eco de teste")
        self.assertEqual(self.history.get("sessao1"), [
            {"role": "user", "content": "oi"},
            {"role": "assistant", "content": "eco de teste"},
        ])

    def test_rejects_empty_and_oversized_messages(self):
        with self.assertRaises(ValueError):
            self.agent.respond("sessao1", " ")
        with self.assertRaises(ValueError):
            self.agent.respond("sessao1", "x" * 12_001)

    def test_tool_call_cycle_is_bounded_and_recorded(self):
        provider = FakeProvider([
            {"content": None, "tool_calls": [{
                "id": "call1", "type": "function",
                "function": {"name": "calculate", "arguments": '{"expression":"(8+4)*3"}'},
            }]},
            {"content": "O resultado é 36.", "tool_calls": []},
        ])
        agent = Agent(provider, self.history)
        answer = agent.respond("math", "Quanto dá (8+4)*3?")
        self.assertEqual(answer, "O resultado é 36.")
        self.assertEqual(provider.requests[1][-1]["content"], "36")

    def test_delete_session_memory(self):
        self.agent.respond("apagar", "olá")
        self.assertEqual(self.history.delete("apagar"), 2)
        self.assertEqual(self.history.get("apagar"), [])


class SecurityTests(unittest.TestCase):
    def test_optional_bearer_token(self):
        self.assertTrue(authorization_valid("", ""))
        self.assertTrue(authorization_valid("Bearer secret", "secret"))
        self.assertFalse(authorization_valid("Bearer wrong", "secret"))


class ToolTests(unittest.TestCase):
    def test_safe_calculator(self):
        self.assertEqual(calculate({"expression": "(8 + 4) * 3"}), "36")
        with self.assertRaises(ToolError):
            calculate({"expression": "__import__('os').system('id')"})


if __name__ == "__main__":
    unittest.main()
