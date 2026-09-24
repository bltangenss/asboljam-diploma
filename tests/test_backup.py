"""Backup guarantees against active WAL, tampering and accidental replacement."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.backup_db import copy_database, inspect_database


class BackupTests(unittest.TestCase):
    def setUp(self):
        Path(".cache").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="backup-test-", dir=".cache")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.sqlite"
        self.connection = sqlite3.connect(self.source)
        self.addCleanup(self.connection.close)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        self.connection.execute("INSERT INTO records VALUES (1, 'Қалдық – бастапқы мән')")
        self.connection.commit()

    def test_online_backup_includes_committed_wal_and_restore_preserves_data(self):
        self.assertTrue(self.source.with_suffix(".sqlite-wal").exists())
        backup = self.root / "backup.sqlite"
        result = copy_database(self.source, backup)
        self.assertEqual(result["integrity_check"], "ok")
        self.assertEqual(result["table_rows"], {"records": 1})
        self.connection.execute("INSERT INTO records VALUES (2, 'later change')")
        self.connection.commit()
        restored = self.root / "restored.sqlite"
        restored_report = copy_database(backup, restored, "restore")
        self.assertEqual(restored_report["table_rows"], {"records": 1})
        with closing(sqlite3.connect(restored)) as database:
            self.assertEqual(database.execute("SELECT value FROM records WHERE id=1").fetchone()[0],
                             "Қалдық – бастапқы мән")
        self.assertEqual(inspect_database(self.source)["table_rows"]["records"], 2)

    def test_existing_destination_never_overwritten(self):
        target = self.root / "existing.sqlite"
        target.write_bytes(b"must remain unchanged")
        with self.assertRaises(FileExistsError):
            copy_database(self.source, target)
        self.assertEqual(target.read_bytes(), b"must remain unchanged")
        with self.assertRaises(ValueError):
            copy_database(self.source, self.source)

    def test_tampered_backup_manifest_rejected_before_restore(self):
        backup = self.root / "backup.sqlite"
        copy_database(self.source, backup)
        manifest = backup.with_suffix(".sqlite.manifest.json")
        report = json.loads(manifest.read_text(encoding="utf-8"))
        report["sha256"] = "0" * 64
        manifest.write_text(json.dumps(report), encoding="utf-8")
        target = self.root / "restore.sqlite"
        with self.assertRaisesRegex(ValueError, "SHA256"):
            copy_database(backup, target, "restore")
        self.assertFalse(target.exists())

    def test_corrupt_database_rejected(self):
        corrupt = self.root / "corrupt.sqlite"
        corrupt.write_bytes(b"not a database")
        target = self.root / "restore.sqlite"
        with self.assertRaises(sqlite3.DatabaseError):
            copy_database(corrupt, target, "restore")
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
