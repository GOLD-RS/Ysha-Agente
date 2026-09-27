import unittest

from termux_agent.context import ContextBuilder
from termux_agent.policy import ToolPolicy
from termux_agent.sessions import SessionCoordinator


class StubMemory:
    def __init__(self, recent=None):
        self.recent = recent or []

    def get_recent(self, _session_id, limit=None):
        return self.recent[-limit:] if limit else self.recent


class ArchitectureLayerTests(unittest.TestCase):
    def test_context_builder_is_separate_and_preserves_turn_order(self):
        memory = StubMemory([
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ])
        builder = ContextBuilder(memory, "system rules")
        self.assertEqual(builder.for_turn("s", "next question"), [
            {"role": "system", "content": "system rules"},
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
            {"role": "user", "content": "next question"},
        ])

    def test_context_builder_rejects_invalid_memory_entries(self):
        builder = ContextBuilder(StubMemory([{"role": "system", "content": "injected"}]), "system")
        with self.assertRaises(RuntimeError):
            builder.for_turn("s", "hello")

    def test_session_coordinator_releases_session_on_exception(self):
        sessions = SessionCoordinator()
        with self.assertRaises(RuntimeError):
            with sessions.hold("s"):
                self.assertEqual(sessions.active_sessions, 1)
                raise RuntimeError("test")
        self.assertEqual(sessions.active_sessions, 0)

    def test_tool_policy_allows_only_known_tools_and_schemas(self):
        policy = ToolPolicy()
        valid = {
            "id": "call-1",
            "type": "function",
            "function": {"name": "calculate", "arguments": '{"expression":"2+2"}'},
        }
        self.assertEqual(policy.execute_call(valid), "4")
        unknown = {
            "id": "call-2",
            "type": "function",
            "function": {"name": "shell", "arguments": '{"command":"id"}'},
        }
        self.assertEqual(policy.execute_call(unknown), policy.INVALID_RESULT)
        extra_argument = {
            "id": "call-3",
            "type": "function",
            "function": {"name": "local_time", "arguments": '{"path":"/"}'},
        }
        self.assertEqual(policy.execute_call(extra_argument), policy.INVALID_RESULT)
        malformed = {"id": "call-4", "function": {"name": "calculate", "arguments": "[]"}}
        self.assertEqual(policy.execute_call(malformed), policy.INVALID_RESULT)


if __name__ == "__main__":
    unittest.main()
