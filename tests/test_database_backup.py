from pathlib import Path
import stat
import tempfile
import unittest

from termux_agent.db_maintenance import (
    DatabaseLock,
    DatabaseMaintenanceError,
    backup_database,
    restore_database,
    verify_database,
)
from termux_agent.history import HistoryStore


class DatabaseMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "memory.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def add_exchange(self, path, session, user, assistant):
        history = HistoryStore(str(path))
        try:
            history.add_exchange(session, user, assistant)
        finally:
            history.close()

    def get_transcript(self, path, session):
        history = HistoryStore(str(path))
        try:
            return history.get(session)
        finally:
            history.close()

    def test_backup_uses_verified_private_snapshot_and_refuses_overwrite(self):
        self.add_exchange(self.database, "s", "before", "reply-before")
        destination = self.root / "saved.sqlite3"
        result = backup_database(self.database, destination)
        self.assertEqual(result, destination)
        self.assertTrue(verify_database(destination))
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertEqual(self.get_transcript(destination, "s")[0]["content"], "before")
        original = destination.read_bytes()
        with self.assertRaises(DatabaseMaintenanceError):
            backup_database(self.database, destination)
        self.assertEqual(destination.read_bytes(), original)

    def test_restore_requires_confirmation_and_preserves_previous_database(self):
        self.add_exchange(self.database, "s", "snapshot", "saved-answer")
        backup = backup_database(self.database, self.root / "snapshot.sqlite3")
        self.add_exchange(self.database, "s", "later", "later-answer")

        with self.assertRaises(DatabaseMaintenanceError):
            restore_database(backup, self.database)
        self.assertEqual(len(self.get_transcript(self.database, "s")), 4)

        previous = restore_database(backup, self.database, confirmed=True)
        self.assertIsNotNone(previous)
        self.assertTrue(verify_database(self.database))
        self.assertEqual(
            [item["content"] for item in self.get_transcript(self.database, "s")],
            ["snapshot", "saved-answer"],
        )
        self.assertEqual(
            [item["content"] for item in self.get_transcript(previous, "s")],
            ["snapshot", "saved-answer", "later", "later-answer"],
        )
        self.assertEqual(stat.S_IMODE(previous.stat().st_mode), 0o600)

    def test_corrupt_backup_does_not_touch_existing_memory(self):
        self.add_exchange(self.database, "s", "kept", "reply")
        corrupt = self.root / "corrupt.sqlite3"
        corrupt.write_bytes(b"not a sqlite database")
        with self.assertRaises(DatabaseMaintenanceError):
            restore_database(corrupt, self.database, confirmed=True)
        self.assertEqual(
            [item["content"] for item in self.get_transcript(self.database, "s")],
            ["kept", "reply"],
        )

    def test_restore_refuses_while_agent_holds_shared_lock(self):
        self.add_exchange(self.database, "s", "kept", "reply")
        backup = backup_database(self.database, self.root / "snapshot.sqlite3")
        with DatabaseLock(self.database, exclusive=False):
            with self.assertRaisesRegex(DatabaseMaintenanceError, "Pare o agente"):
                restore_database(backup, self.database, confirmed=True)
        self.assertEqual(
            [item["content"] for item in self.get_transcript(self.database, "s")],
            ["kept", "reply"],
        )

    def test_restore_to_new_database_creates_verified_copy(self):
        self.add_exchange(self.database, "s", "saved", "answer")
        backup = backup_database(self.database, self.root / "snapshot.sqlite3")
        target = self.root / "new.sqlite3"
        self.assertIsNone(restore_database(backup, target, confirmed=True))
        self.assertTrue(verify_database(target))
        self.assertEqual(self.get_transcript(target, "s")[0]["content"], "saved")


if __name__ == "__main__":
    unittest.main()
