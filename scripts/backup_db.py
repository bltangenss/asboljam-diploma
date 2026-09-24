"""Verified SQLite online backups and restore into a NEW database file.

Examples:
  python scripts/backup_db.py backup --database data/asboljam.sqlite --output backups/demo.sqlite
  python scripts/backup_db.py restore --backup backups/demo.sqlite --destination data/restored.sqlite

For PostgreSQL use pg_dump --format=custom and pg_restore into a new database;
this utility deliberately operates only on SQLite database files.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_database(path: Path) -> dict:
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise ValueError("SQLite integrity check failed: " + "; ".join(integrity[:5]))
        foreign_key_errors = list(connection.execute("PRAGMA foreign_key_check"))
        if foreign_key_errors:
            raise ValueError("SQLite foreign-key check failed")
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {}
        for name in names:
            identifier = '"' + name.replace('"', '""') + '"'
            counts[name] = connection.execute("SELECT COUNT(*) FROM " + identifier).fetchone()[0]
        return {"integrity_check": "ok", "foreign_key_check": "ok", "table_rows": counts}


def copy_database(source: Path, destination: Path, operation: str = "backup") -> dict:
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    manifest_path = destination.with_suffix(destination.suffix + ".manifest.json")
    if operation not in ("backup", "restore"):
        raise ValueError("operation must be backup or restore")
    if source == destination:
        raise ValueError("Source and destination must be different")
    if destination.exists() or manifest_path.exists():
        raise FileExistsError("Destination or its manifest already exists; choose a new file")
    if operation == "restore":
        expected_path = source.with_suffix(source.suffix + ".manifest.json")
        if expected_path.exists():
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            if expected.get("sha256") != _sha256(source):
                raise ValueError("Backup SHA256 does not match its manifest")
    # Check source first; a corrupted input must not leave an apparent restore.
    source_report = inspect_database(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb"):
        pass  # Exclusive reservation also rejects a concurrent name collision.
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=30)) as reader:
            with closing(sqlite3.connect(destination, timeout=30)) as writer:
                reader.backup(writer, pages=256, sleep=0.01)
        report = inspect_database(destination)
        # Counts can legitimately change in a live source after preflight. The
        # destination is itself one consistent SQLite online-backup snapshot.
        result = {
            "operation": operation, "created_at": datetime.now(timezone.utc).isoformat(),
            "source": str(source), "destination": str(destination),
            "sha256": _sha256(destination), "sqlite_version": sqlite3.sqlite_version,
            "source_preflight": source_report, **report,
            "method": "SQLite online backup API, including committed WAL transactions",
        }
        with manifest_path.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return result
    except Exception:
        # Only remove the new destination reserved by this invocation.
        destination.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    actions = parser.add_subparsers(dest="operation", required=True)
    backup = actions.add_parser("backup", help="Create a verified consistent SQLite backup")
    backup.add_argument("--database", required=True, type=Path)
    backup.add_argument("--output", required=True, type=Path)
    restore = actions.add_parser("restore", help="Restore and verify into a new destination")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    if args.operation == "backup":
        result = copy_database(args.database, args.output, "backup")
    else:
        result = copy_database(args.backup, args.destination, "restore")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
