from contextlib import closing
import sqlite3
import tempfile
import threading
import time
import unittest

from termux_agent.agent import Agent
from termux_agent.history import HistoryStore
from termux_agent.provider import ProviderError
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


class SlowProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(list(messages))
        time.sleep(0.04)
        return {"content": "resposta", "tool_calls": []}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.history = HistoryStore(f"{self.temp.name}/memory.sqlite3", limit=6)
        self.provider = FakeProvider()
        self.agent = Agent(self.provider, self.history)

    def tearDown(self):
        self.history.close()
        self.temp.cleanup()

    def test_saves_conversation_and_reuses_context(self):
        self.assertEqual(self.agent.respond("sessao1", "  oi  "), "eco de teste")
        self.assertEqual(self.history.get("sessao1"), [
            {"role": "user", "content": "oi"},
            {"role": "assistant", "content": "eco de teste"},
        ])

    def test_malformed_provider_messages_fail_safely_without_saving_partial_turns(self):
        malformed = [
            {"content": [], "tool_calls": []},
            {"content": None, "tool_calls": [{"type": "function", "function": {"name": "calculate", "arguments": "{}"}}]},
        ]
        for response in malformed:
            with self.subTest(response=response):
                agent = Agent(FakeProvider([response]), self.history)
                with self.assertRaises(ProviderError):
                    agent.respond("malformed", "test")
                self.assertEqual(self.history.get("malformed"), [])

    def test_existing_database_is_migrated_additively_without_losing_rows(self):
        path = f"{self.temp.name}/old-schema.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            with db:
                db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at INTEGER NOT NULL)")
                db.executemany(
                    "INSERT INTO messages(session_id, role, content, created_at) VALUES(?,?,?,?)",
                    [("legacy", "user", "antes", 1), ("legacy", "assistant", "resposta antiga", 2)],
                )
        history = HistoryStore(path, limit=2)
        self.addCleanup(history.close)
        self.assertEqual(history.get("legacy"), [
            {"role": "user", "content": "antes"},
            {"role": "assistant", "content": "resposta antiga"},
        ])
        with history._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM message_archives").fetchone()[0], 0)

    def test_full_transcript_is_preserved_while_prompt_context_stays_bounded(self):
        history = HistoryStore(f"{self.temp.name}/full.sqlite3", limit=2)
        self.addCleanup(history.close)
        provider = FakeProvider([
            {"content": "resposta 1", "tool_calls": []},
            {"content": "resposta 2", "tool_calls": []},
            {"content": "resposta 3", "tool_calls": []},
        ])
        agent = Agent(provider, history)
        for message in ("um", "dois", "três"):
            agent.respond("persistente", message)
        self.assertEqual(len(history.get("persistente")), 6)
        self.assertEqual(history.get_recent("persistente", 2), [
            {"role": "user", "content": "três"},
            {"role": "assistant", "content": "resposta 3"},
        ])
        next_provider = FakeProvider()
        Agent(next_provider, history).respond("persistente", "quatro")
        self.assertEqual(next_provider.requests[0][1:], [
            {"role": "user", "content": "três"},
            {"role": "assistant", "content": "resposta 3"},
            {"role": "user", "content": "quatro"},
        ])

    def test_old_transcript_chunks_are_compressed_without_loss(self):
        history = HistoryStore(
            f"{self.temp.name}/archive.sqlite3",
            limit=2,
            archive_trigger=4,
            archive_keep=2,
            archive_batch=2,
        )
        self.addCleanup(history.close)
        for number in range(3):
            history.add_exchange("archive", f"pergunta {number}", f"resposta {number}")
        self.assertEqual(len(history.get("archive")), 6)
        self.assertEqual(history.get_recent("archive", 2)[-1]["content"], "resposta 2")
        with history._connect() as db:
            hot_count = db.execute("SELECT COUNT(*) FROM messages WHERE session_id='archive'").fetchone()[0]
            archived_count = db.execute("SELECT SUM(message_count) FROM message_archives WHERE session_id='archive'").fetchone()[0]
        self.assertEqual(hot_count, 4)
        self.assertEqual(archived_count, 2)
        self.assertEqual(history.delete("archive"), 6)
        self.assertEqual(history.get("archive"), [])

    def test_corrupt_archive_is_reported_instead_of_silently_dropped(self):
        history = HistoryStore(
            f"{self.temp.name}/corrupt.sqlite3",
            limit=2,
            archive_trigger=4,
            archive_keep=2,
            archive_batch=2,
        )
        self.addCleanup(history.close)
        for number in range(3):
            history.add_exchange("corrupt", f"q{number}", f"a{number}")
        with history._connect() as db:
            db.execute("UPDATE message_archives SET compressed_payload=? WHERE session_id=?", (b"broken", "corrupt"))
        with self.assertRaisesRegex(RuntimeError, "bloco compactado inválido"):
            history.get("corrupt")

    def test_in_memory_history_remains_available_across_operations(self):
        history = HistoryStore(":memory:", limit=2)
        try:
            history.add_exchange("memory", "pergunta", "resposta")
            self.assertEqual(history.get("memory"), [
                {"role": "user", "content": "pergunta"},
                {"role": "assistant", "content": "resposta"},
            ])
        finally:
            history.close()

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

    def test_parallel_requests_for_same_session_keep_ordered_context(self):
        provider = SlowProvider()
        agent = Agent(provider, self.history)
        start = threading.Barrier(3)

        def send(text):
            start.wait()
            agent.respond("shared", text)

        threads = [threading.Thread(target=send, args=(word,)) for word in ("um", "dois")]
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join(timeout=2)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertTrue(any(any(item["role"] == "assistant" for item in req) for req in provider.requests[1:]))
        self.assertEqual(agent.sessions.active_sessions, 0)


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
