from __future__ import annotations

from typing import Iterable

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


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

    This is a lightweight safety net for local/dev SQLite DBs.

    The project currently relies on `Base.metadata.create_all` + this best-effort
    forward migration layer (instead of Alembic) to keep installs usable across
    versions.
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
        _add_col(
            conn, table="question_library", name="starred", ddl="INTEGER NOT NULL DEFAULT 0", existing_cols=ql_cols
        )
        _ensure_index(conn, name="ix_question_library_subject", table="question_library", columns="subject")
        _ensure_index(conn, name="ix_question_library_origin", table="question_library", columns="origin")
        _ensure_index(conn, name="ix_question_library_hidden", table="question_library", columns="hidden")
        _ensure_index(conn, name="ix_question_library_starred", table="question_library", columns="starred")

    # Unified tasks additions (best-effort forward-compat).
    tasks_cols = _table_cols(conn, "tasks")
    if tasks_cols:
        _add_col(conn, table="tasks", name="last_seq", ddl="INTEGER NOT NULL DEFAULT 0", existing_cols=tasks_cols)
        _ensure_index(conn, name="ix_tasks_user_id", table="tasks", columns="user_id")
        _ensure_index(conn, name="ix_tasks_task_type", table="tasks", columns="task_type")
        _ensure_index(conn, name="ix_tasks_status", table="tasks", columns="status")
        _ensure_index(conn, name="ix_tasks_updated_at", table="tasks", columns="updated_at")

    # Study archive versioning: introduce deterministic base_fingerprint for cache lookup.
    sa_cols = _table_cols(conn, "study_archives")
    if sa_cols:
        _add_col(
            conn,
            table="study_archives",
            name="base_fingerprint",
            ddl="VARCHAR(32) NOT NULL DEFAULT ''",
            existing_cols=sa_cols,
        )
        _ensure_index(
            conn, name="ix_study_archives_base_fingerprint", table="study_archives", columns="base_fingerprint"
        )
        try:
            conn.exec_driver_sql(
                "UPDATE study_archives SET base_fingerprint = fingerprint "
                "WHERE base_fingerprint IS NULL OR base_fingerprint = ''"
            )
        except Exception:
            logger.warning("legacy_migration_base_fingerprint_backfill_failed", exc_info=True)

    # Full-text search (SQLite FTS5) — best-effort. If the runtime SQLite build lacks FTS5,
    # we silently skip and fall back to LIKE-based search in the API.
    try:
        conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
            "user_id UNINDEXED,"
            "conversation_id UNINDEXED,"
            "message_id UNINDEXED,"
            "title UNINDEXED,"
            "content,"
            "tokenize='unicode61 remove_diacritics 2'"
            ")"
        )
        conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS paper_questions_fts USING fts5("
            "user_id UNINDEXED,"
            "paper_id UNINDEXED,"
            "question_id UNINDEXED,"
            "paper_name UNINDEXED,"
            "knowledge_point UNINDEXED,"
            "content,"
            "tokenize='unicode61 remove_diacritics 2'"
            ")"
        )
        conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS study_archives_fts USING fts5("
            "user_id UNINDEXED,"
            "archive_id UNINDEXED,"
            "subject,"
            "topic,"
            "requirements,"
            "markdown,"
            "tokenize='unicode61 remove_diacritics 2'"
            ")"
        )

        # messages → messages_fts (exclude tool messages by default)
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages "
            "WHEN NEW.role <> 'tool' "
            "BEGIN "
            "INSERT INTO messages_fts(rowid,user_id,conversation_id,message_id,title,content) "
            "VALUES("
            "NEW.id,"
            "(SELECT user_id FROM conversations WHERE id=NEW.conversation_id),"
            "NEW.conversation_id,"
            "NEW.id,"
            "(SELECT title FROM conversations WHERE id=NEW.conversation_id),"
            "NEW.content"
            "); "
            "END;"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages "
            "BEGIN "
            "DELETE FROM messages_fts WHERE rowid=OLD.id; "
            "END;"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages "
            "BEGIN "
            "DELETE FROM messages_fts WHERE rowid=OLD.id; "
            "INSERT INTO messages_fts(rowid,user_id,conversation_id,message_id,title,content) "
            "SELECT "
            "NEW.id,"
            "(SELECT user_id FROM conversations WHERE id=NEW.conversation_id),"
            "NEW.conversation_id,"
            "NEW.id,"
            "(SELECT title FROM conversations WHERE id=NEW.conversation_id),"
            "NEW.content "
            "WHERE NEW.role <> 'tool'; "
            "END;"
        )

        # paper_questions → paper_questions_fts
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS paper_questions_ai AFTER INSERT ON paper_questions "
            "BEGIN "
            "INSERT INTO paper_questions_fts(rowid,user_id,paper_id,question_id,paper_name,knowledge_point,content) "
            "VALUES("
            "NEW.id,"
            "(SELECT user_id FROM papers WHERE id=NEW.paper_id),"
            "NEW.paper_id,"
            "NEW.question_id,"
            "(SELECT name FROM papers WHERE id=NEW.paper_id),"
            "NEW.knowledge_point,"
            "COALESCE(NEW.knowledge_point,'') || char(10) || COALESCE(NEW.stem,'') || char(10) || COALESCE(NEW.analysis,'')"
            "); "
            "END;"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS paper_questions_ad AFTER DELETE ON paper_questions "
            "BEGIN "
            "DELETE FROM paper_questions_fts WHERE rowid=OLD.id; "
            "END;"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS paper_questions_au AFTER UPDATE ON paper_questions "
            "BEGIN "
            "DELETE FROM paper_questions_fts WHERE rowid=OLD.id; "
            "INSERT INTO paper_questions_fts(rowid,user_id,paper_id,question_id,paper_name,knowledge_point,content) "
            "VALUES("
            "NEW.id,"
            "(SELECT user_id FROM papers WHERE id=NEW.paper_id),"
            "NEW.paper_id,"
            "NEW.question_id,"
            "(SELECT name FROM papers WHERE id=NEW.paper_id),"
            "NEW.knowledge_point,"
            "COALESCE(NEW.knowledge_point,'') || char(10) || COALESCE(NEW.stem,'') || char(10) || COALESCE(NEW.analysis,'')"
            "); "
            "END;"
        )

        # study_archives → study_archives_fts
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS study_archives_ai AFTER INSERT ON study_archives "
            "BEGIN "
            "INSERT INTO study_archives_fts(rowid,user_id,archive_id,subject,topic,requirements,markdown) "
            "VALUES(NEW.id, NEW.user_id, NEW.id, NEW.subject, NEW.topic, NEW.requirements, NEW.markdown); "
            "END;"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS study_archives_ad AFTER DELETE ON study_archives "
            "BEGIN "
            "DELETE FROM study_archives_fts WHERE rowid=OLD.id; "
            "END;"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS study_archives_au AFTER UPDATE ON study_archives "
            "BEGIN "
            "DELETE FROM study_archives_fts WHERE rowid=OLD.id; "
            "INSERT INTO study_archives_fts(rowid,user_id,archive_id,subject,topic,requirements,markdown) "
            "VALUES(NEW.id, NEW.user_id, NEW.id, NEW.subject, NEW.topic, NEW.requirements, NEW.markdown); "
            "END;"
        )

        def _fts_has_any(table: str) -> bool:
            try:
                row = conn.exec_driver_sql(f"SELECT 1 FROM {table} LIMIT 1").first()
                return row is not None
            except Exception:
                return False

        # Backfill is expensive on large DBs. Run it only when the FTS tables are empty
        # (newly created) or missing. Triggers will keep them up-to-date afterwards.
        if not _fts_has_any("messages_fts"):
            conn.exec_driver_sql(
                "INSERT OR REPLACE INTO messages_fts(rowid,user_id,conversation_id,message_id,title,content) "
                "SELECT m.id, c.user_id, m.conversation_id, m.id, c.title, m.content "
                "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                "WHERE m.role <> 'tool'"
            )
        if not _fts_has_any("paper_questions_fts"):
            conn.exec_driver_sql(
                "INSERT OR REPLACE INTO paper_questions_fts(rowid,user_id,paper_id,question_id,paper_name,knowledge_point,content) "
                "SELECT pq.id, p.user_id, pq.paper_id, pq.question_id, p.name, pq.knowledge_point, "
                "COALESCE(pq.knowledge_point,'') || char(10) || COALESCE(pq.stem,'') || char(10) || COALESCE(pq.analysis,'') "
                "FROM paper_questions pq JOIN papers p ON p.id=pq.paper_id"
            )
        if not _fts_has_any("study_archives_fts"):
            conn.exec_driver_sql(
                "INSERT OR REPLACE INTO study_archives_fts(rowid,user_id,archive_id,subject,topic,requirements,markdown) "
                "SELECT id, user_id, id, subject, topic, requirements, markdown FROM study_archives"
            )
    except Exception:
        return
