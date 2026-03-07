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


def _ensure_index(conn, *, name: str, table: str, columns: str) -> None:
    try:
        conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")
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

    # User scoping (multi-user isolation):
    # - Older installations had no `user_id` for these tables (effectively global storage).
    # - Add `user_id` with a conservative default ('1' == bootstrap admin user id).
    for table, idx in (
        ("papers", "ix_papers_user_id"),
        ("conversations", "ix_conversations_user_id"),
        ("canvas_boards", "ix_canvas_boards_user_id"),
        ("search_history", "ix_search_history_user_id"),
    ):
        cols = _table_cols(conn, table)
        if not cols:
            continue
        _add_col(conn, table=table, name="user_id", ddl="VARCHAR(64) NOT NULL DEFAULT '1'", existing_cols=cols)
        _ensure_index(conn, name=idx, table=table, columns="user_id")

    # Question library incremental additions.
    ql_cols = _table_cols(conn, "question_library")
    if ql_cols:
        _add_col(conn, table="question_library", name="starred", ddl="INTEGER NOT NULL DEFAULT 0", existing_cols=ql_cols)
        _ensure_index(conn, name="ix_question_library_subject", table="question_library", columns="subject")
        _ensure_index(conn, name="ix_question_library_origin", table="question_library", columns="origin")
        _ensure_index(conn, name="ix_question_library_hidden", table="question_library", columns="hidden")
        _ensure_index(conn, name="ix_question_library_starred", table="question_library", columns="starred")
