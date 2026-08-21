from __future__ import annotations

import gc
import sqlite3
import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "database" / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(ROOT))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


class TestDatabaseAlembic(unittest.TestCase):
    def test_paper_question_user_id_migration_upgrade_and_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "CREATE TABLE papers ("
                    "id INTEGER PRIMARY KEY, "
                    "user_id VARCHAR(64) NOT NULL, "
                    "paper_name VARCHAR(200) NOT NULL"
                    ")"
                )
                conn.execute(
                    "CREATE TABLE paper_questions ("
                    "id INTEGER PRIMARY KEY, "
                    "paper_id INTEGER NOT NULL, "
                    "question_id VARCHAR(50) NOT NULL, "
                    "question_order INTEGER"
                    ")"
                )
                conn.execute("INSERT INTO papers (id, user_id, paper_name) VALUES (1, 'user-a', 'A')")
                conn.execute(
                    "INSERT INTO paper_questions (id, paper_id, question_id, question_order) "
                    "VALUES (1, 1, 'q1', 1)"
                )
                conn.commit()
            finally:
                conn.close()

            cfg = _alembic_config(db_path)
            command.upgrade(cfg, "head")

            self.assertIn("user_id", _columns(db_path, "paper_questions"))
            self.assertEqual(
                _columns(db_path, "gaokao_question_sources"),
                {
                    "user_id",
                    "question_id",
                    "exam_year",
                    "region",
                    "paper_name",
                    "paper_variant",
                    "question_number",
                    "source_url",
                    "source_note",
                    "verified",
                    "created_at",
                    "updated_at",
                },
            )
            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute("SELECT user_id FROM paper_questions WHERE id = 1").fetchone()
                indexes = {str(item[1]) for item in conn.execute("PRAGMA index_list(paper_questions)").fetchall()}
            finally:
                conn.close()
            self.assertEqual(row, ("user-a",))
            self.assertIn("ix_paper_questions_user_question", indexes)

            command.downgrade(cfg, "0001_initial")
            self.assertNotIn("user_id", _columns(db_path, "paper_questions"))
            gc.collect()


if __name__ == "__main__":
    unittest.main()
