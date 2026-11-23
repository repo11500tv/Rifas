"""Real SQLite snapshot/rollback on disposable directories only."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from deployment import backup_integral as snapshot


class SQLiteRollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "environment"
        self.root.mkdir()
        (self.root / "central").mkdir()
        (self.root / "entidades").mkdir()
        self.db = self.root / "central" / "plataforma.sqlite"
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TABLE raffle (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
            conn.execute("INSERT INTO raffle VALUES (1, 'original')")
        self.events = []
        self.backup = Path(self.temp.name) / "snapshot"

    def test_sqlite_rollback_restores_rows_and_schema(self):
        fingerprint = snapshot.capture(
            self.root, None, [], [Path("central/plataforma.sqlite")],
            self.backup, lambda *args, **kwargs: self.events.append(args),
        )
        snapshot.verify(self.backup, fingerprint)
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE raffle SET status='changed' WHERE id=1")
            conn.execute("INSERT INTO raffle VALUES (2, 'new')")
            conn.execute("CREATE TABLE extra (value TEXT)")
        (self.root / "central" / "unexpected.txt").write_text("new release artifact")
        snapshot.restore(
            self.root, None, [], [Path("central/plataforma.sqlite")],
            self.backup, fingerprint, lambda *args, **kwargs: self.events.append(args),
        )
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT * FROM raffle").fetchall(), [(1, "original")])
            self.assertEqual(conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall(), [("raffle",)])
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertFalse((self.root / "central" / "unexpected.txt").exists())

    def test_corrupted_backup_blocks_restoration(self):
        fingerprint = snapshot.capture(
            self.root, None, [], [Path("central/plataforma.sqlite")],
            self.backup, lambda *args, **kwargs: None,
        )
        (self.backup / "data" / "central" / "plataforma.sqlite").write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            snapshot.restore(
                self.root, None, [], [Path("central/plataforma.sqlite")],
                self.backup, fingerprint, lambda *args, **kwargs: None,
            )
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT status FROM raffle").fetchone()[0], "original")


if __name__ == "__main__":
    unittest.main()
