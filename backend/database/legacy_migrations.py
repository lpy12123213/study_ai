from __future__ import annotations

from typing import Iterable


def _table_cols(conn, table: str) -> list[str]:
    try:
        return [r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []


def _add_col(conn, *, table: str, name: str, ddl: str, existing_cols: Iterable[str]) -> None:
    if name in set(existing_cols):
        return
    try:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    except Exception:
        return


def sync_migrate_db_schema(conn) -> None:
    """Best-effort SQLite schema migrations for existing installations.

    This is a lightweight safety net for local/dev DBs. For traceable schema
    evolution, prefer Alembic migrations (see `alembic/`).
    """

    pq_cols = _table_cols(conn, "paper_questions")
    if pq_cols:
        for name, ddl in (
            ("stem", "TEXT"),
            ("stem_fingerprint", "VARCHAR(32)"),
            ("difficulty_value", "FLOAT"),
            ("quality_score", "INTEGER"),
            ("quality_flags", "TEXT"),
            ("knowledge_points_json", "TEXT"),
            ("source", "VARCHAR(200)"),
            ("date", "VARCHAR(50)"),
            ("answer", "TEXT"),
            ("analysis", "TEXT"),
        ):
            _add_col(conn, table="paper_questions", name=name, ddl=ddl, existing_cols=pq_cols)

