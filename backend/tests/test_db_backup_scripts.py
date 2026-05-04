from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _exec_sql(db_path: Path, statements: list[str]) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        for statement in statements:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


def _fetch_one(db_path: Path, query: str):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(query).fetchone()
    finally:
        conn.close()


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed_to_load_script: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDbBackupScripts(unittest.TestCase):
    def test_backup_and_restore_round_trip(self) -> None:
        backup_script = _load_script("backup_db.py")
        restore_script = _load_script("restore_db.py")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "source.db"
            restored = tmp / "restored.db"
            out_dir = tmp / "backups"

            _exec_sql(
                db,
                [
                    "CREATE TABLE demo(id INTEGER PRIMARY KEY, name TEXT NOT NULL);",
                    "INSERT INTO demo(name) VALUES ('alpha');",
                ],
            )

            backup = backup_script.backup_database(db_path=db, output_dir=out_dir, name="unit")
            self.assertTrue(backup.exists())

            result = restore_script.restore_database(backup_path=backup, db_path=restored, yes=True)
            self.assertTrue(result["ok"])

            row = _fetch_one(restored, "SELECT name FROM demo WHERE id = 1")
            self.assertEqual(row[0], "alpha")

    def test_restore_requires_explicit_yes(self) -> None:
        restore_script = _load_script("restore_db.py")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backup = tmp / "backup.db"
            target = tmp / "target.db"
            _exec_sql(backup, ["CREATE TABLE demo(id INTEGER);"])

            with self.assertRaises(RuntimeError):
                restore_script.restore_database(backup_path=backup, db_path=target, yes=False)
