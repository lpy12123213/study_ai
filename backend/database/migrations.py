from __future__ import annotations

from typing import Iterable

from sqlalchemy.exc import SQLAlchemyError

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


def _table_cols(conn, table: str) -> list[str]:
    try:
        return [r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()]
    except (IndexError, SQLAlchemyError, TypeError):
        return []


def _add_col(conn, *, table: str, name: str, ddl: str, existing_cols: Iterable[str]) -> None:
    if name in set(existing_cols):
        return
    try:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    except SQLAlchemyError:
        logger.warning("migration: failed to add column %s.%s (%s)", table, name, ddl, exc_info=True)
        return


def _ensure_index(conn, *, name: str, table: str, columns: str) -> None:
    try:
        conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")
    except SQLAlchemyError:
        logger.warning("migration: failed to create index %s on %s (%s)", name, table, columns, exc_info=True)
        return


def sync_migrate_db_schema(conn) -> None:
    """Best-effort SQLite schema migrations for existing installations.

    This is a lightweight safety net for local/dev SQLite DBs.

    The project currently relies on `Base.metadata.create_all` + this best-effort
    forward migration layer (instead of Alembic) to keep installs usable across
    versions.
    """

    try:
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS task_duration_aggregates ("
            "task_type VARCHAR(50) PRIMARY KEY NOT NULL,"
            "completed_count INTEGER NOT NULL DEFAULT 0,"
            "duration_sum_seconds FLOAT NOT NULL DEFAULT 0,"
            "duration_ema_seconds FLOAT NOT NULL DEFAULT 0,"
            "last_duration_seconds FLOAT NOT NULL DEFAULT 0,"
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_task_duration_aggregates_updated_at "
            "ON task_duration_aggregates (updated_at)"
        )
    except Exception:
        logger.warning("legacy_migration_task_duration_aggregate_failed", exc_info=True)

    pq_cols = _table_cols(conn, "paper_questions")
    if pq_cols:
        _add_col(
            conn,
            table="paper_questions",
            name="user_id",
            ddl="VARCHAR(64) NOT NULL DEFAULT ''",
            existing_cols=pq_cols,
        )
        _ensure_index(conn, name="ix_paper_questions_user_id", table="paper_questions", columns="user_id")
        _ensure_index(
            conn,
            name="ix_paper_questions_user_paper_order",
            table="paper_questions",
            columns="user_id, paper_id, question_order",
        )
        _ensure_index(
            conn,
            name="ix_paper_questions_user_question",
            table="paper_questions",
            columns="user_id, question_id",
        )
        try:
            conn.exec_driver_sql(
                "UPDATE paper_questions "
                "SET user_id = COALESCE((SELECT papers.user_id FROM papers WHERE papers.id = paper_questions.paper_id), '') "
                "WHERE user_id IS NULL OR user_id = ''"
            )
        except SQLAlchemyError:
            logger.warning("legacy_migration_paper_questions_user_id_backfill_failed", exc_info=True)

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
        _ensure_index(
            conn,
            name="ix_question_library_user_hidden_updated",
            table="question_library",
            columns="user_id, hidden, updated_at",
        )
        _ensure_index(
            conn,
            name="ix_question_library_user_subject_hidden_updated",
            table="question_library",
            columns="user_id, subject, hidden, updated_at",
        )
        _ensure_index(
            conn,
            name="ix_question_library_user_origin_hidden_updated",
            table="question_library",
            columns="user_id, origin, hidden, updated_at",
        )
        _ensure_index(
            conn,
            name="ix_question_library_user_score_updated",
            table="question_library",
            columns="user_id, ai_score, updated_at",
        )
        try:
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_question_library_unscored_crawled "
                "ON question_library (user_id, subject, question_id) "
                "WHERE origin = 'crawled' AND ai_score IS NULL"
            )
        except Exception:
            logger.warning("legacy_migration_question_library_unscored_index_failed", exc_info=True)

    question_cache_cols = _table_cols(conn, "question_cache")
    if question_cache_cols:
        _add_col(
            conn,
            table="question_cache",
            name="intuition_packet_json",
            ddl="TEXT NOT NULL DEFAULT ''",
            existing_cols=question_cache_cols,
        )
        _add_col(
            conn,
            table="question_cache",
            name="generation_metadata_json",
            ddl="TEXT NOT NULL DEFAULT ''",
            existing_cols=question_cache_cols,
        )

    # Wrongbook SRS scheduling additions.
    wq_cols = _table_cols(conn, "wrong_questions")
    if wq_cols:
        for name, ddl in (
            ("ease_factor", "FLOAT NOT NULL DEFAULT 2.5"),
            ("interval_days", "INTEGER NOT NULL DEFAULT 0"),
            ("repetitions", "INTEGER NOT NULL DEFAULT 0"),
            ("next_review_at", "DATETIME"),
            ("last_reviewed_at", "DATETIME"),
        ):
            _add_col(conn, table="wrong_questions", name=name, ddl=ddl, existing_cols=wq_cols)
        _ensure_index(conn, name="ix_wrong_questions_next_review", table="wrong_questions", columns="next_review_at")
        _ensure_index(
            conn,
            name="ix_wrong_questions_user_next_review",
            table="wrong_questions",
            columns="user_id, next_review_at",
        )

    # Unified tasks additions (best-effort forward-compat).
    tasks_cols = _table_cols(conn, "tasks")
    if tasks_cols:
        _add_col(conn, table="tasks", name="last_seq", ddl="INTEGER NOT NULL DEFAULT 0", existing_cols=tasks_cols)
        _ensure_index(conn, name="ix_tasks_user_id", table="tasks", columns="user_id")
        _ensure_index(conn, name="ix_tasks_task_type", table="tasks", columns="task_type")
        _ensure_index(conn, name="ix_tasks_status", table="tasks", columns="status")
        _ensure_index(conn, name="ix_tasks_updated_at", table="tasks", columns="updated_at")
        _ensure_index(conn, name="ix_tasks_user_status_updated", table="tasks", columns="user_id, status, updated_at")
        _ensure_index(conn, name="ix_tasks_user_type_updated", table="tasks", columns="user_id, task_type, updated_at")
        _ensure_index(
            conn,
            name="ix_tasks_user_type_status_ended",
            table="tasks",
            columns="user_id, task_type, status, ended_at",
        )
        _ensure_index(conn, name="ix_tasks_user_updated", table="tasks", columns="user_id, updated_at")

    task_events_cols = _table_cols(conn, "task_events")
    if task_events_cols:
        _ensure_index(conn, name="ix_task_events_task_id", table="task_events", columns="task_id")
        _ensure_index(conn, name="ix_task_events_task_id_seq", table="task_events", columns="task_id, seq")

    conv_cols = _table_cols(conn, "conversations")
    if conv_cols:
        _ensure_index(
            conn, name="ix_conversations_user_updated", table="conversations", columns="user_id, updated_at"
        )

    message_cols = _table_cols(conn, "messages")
    if message_cols:
        _ensure_index(
            conn, name="ix_messages_conversation_created", table="messages", columns="conversation_id, created_at"
        )
        _ensure_index(conn, name="ix_messages_conversation_id_id", table="messages", columns="conversation_id, id")

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
        _add_col(conn, table="study_archives", name="updated_at", ddl="DATETIME", existing_cols=sa_cols)
        _add_col(
            conn,
            table="study_archives",
            name="acceptance_json",
            ddl="TEXT NOT NULL DEFAULT '{}'",
            existing_cols=sa_cols,
        )
        _ensure_index(
            conn, name="ix_study_archives_base_fingerprint", table="study_archives", columns="base_fingerprint"
        )
        _ensure_index(
            conn, name="ix_study_archives_user_updated", table="study_archives", columns="user_id, updated_at"
        )
        _ensure_index(
            conn,
            name="ix_study_archives_user_base_fingerprint",
            table="study_archives",
            columns="user_id, base_fingerprint",
        )
        _ensure_index(
            conn,
            name="ix_study_archives_user_base_fingerprint_created",
            table="study_archives",
            columns="user_id, base_fingerprint, created_at",
        )
        try:
            conn.exec_driver_sql(
                "UPDATE study_archives SET base_fingerprint = fingerprint "
                "WHERE base_fingerprint IS NULL OR base_fingerprint = ''"
            )
        except Exception:
            logger.warning("legacy_migration_base_fingerprint_backfill_failed", exc_info=True)
        try:
            conn.exec_driver_sql(
                "UPDATE study_archives SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP) "
                "WHERE updated_at IS NULL"
            )
        except Exception:
            logger.warning("legacy_migration_study_archives_updated_at_backfill_failed", exc_info=True)

    # Full-text search (SQLite FTS5) — best-effort. If the runtime SQLite build lacks FTS5,
    # we silently skip and fall back to LIKE-based search in the API.
    try:
        # Legacy FTS tables indexed only long-form content. Rebuild the derived
        # index once so titles, subjects, and knowledge points stay searchable
        # without falling back to slow substring scans.
        legacy_index_markers = {
            "messages_fts": ("title unindexed",),
            "paper_questions_fts": ("paper_name unindexed", "knowledge_point unindexed"),
            "question_library_fts": ("subject unindexed", "knowledge_point unindexed"),
        }
        rebuild_fts = False
        for table, markers in legacy_index_markers.items():
            row = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
                (table,),
            ).first()
            table_sql = str(row[0] or "").lower() if row else ""
            if table_sql and any(marker in table_sql for marker in markers):
                rebuild_fts = True
                break

        if rebuild_fts:
            for trigger in (
                "messages_ai",
                "messages_ad",
                "messages_au",
                "conversations_title_au",
                "paper_questions_ai",
                "paper_questions_ad",
                "paper_questions_au",
                "study_archives_ai",
                "study_archives_ad",
                "study_archives_au",
                "question_library_ai",
                "question_library_ad",
                "question_library_au",
                "question_cache_au_question_library_fts",
            ):
                conn.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger}")
            for table in (
                "messages_fts",
                "paper_questions_fts",
                "study_archives_fts",
                "question_library_fts",
            ):
                conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")

        conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
            "user_id UNINDEXED,"
            "conversation_id UNINDEXED,"
            "message_id UNINDEXED,"
            "title,"
            "content,"
            "tokenize='unicode61 remove_diacritics 2'"
            ")"
        )
        conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS paper_questions_fts USING fts5("
            "user_id UNINDEXED,"
            "paper_id UNINDEXED,"
            "question_id UNINDEXED,"
            "paper_name,"
            "knowledge_point,"
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
        conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS question_library_fts USING fts5("
            "user_id UNINDEXED,"
            "question_id UNINDEXED,"
            "subject,"
            "knowledge_point,"
            "hidden UNINDEXED,"
            "content,"
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

        # conversations → messages_fts title (rename propagates to every message of the conversation)
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS conversations_title_au AFTER UPDATE OF title ON conversations "
            "BEGIN "
            "UPDATE messages_fts SET title = NEW.title WHERE conversation_id = OLD.id; "
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
            "(SELECT paper_name FROM papers WHERE id=NEW.paper_id),"
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
            "(SELECT paper_name FROM papers WHERE id=NEW.paper_id),"
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

        # question_library + question_cache → question_library_fts
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS question_library_ai AFTER INSERT ON question_library "
            "BEGIN "
            "INSERT INTO question_library_fts(user_id,question_id,subject,knowledge_point,hidden,content) "
            "SELECT "
            "NEW.user_id,"
            "NEW.question_id,"
            "COALESCE(NULLIF(NEW.subject,''), NULLIF(qc.subject,''), ''),"
            "COALESCE(qc.knowledge_point,''),"
            "COALESCE(NEW.hidden,0),"
            "COALESCE(qc.stem,'') || char(10) || COALESCE(qc.answer,'') || char(10) || COALESCE(qc.analysis,'') "
            "FROM question_cache qc WHERE qc.question_id = NEW.question_id; "
            "END;"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS question_library_ad AFTER DELETE ON question_library "
            "BEGIN "
            "DELETE FROM question_library_fts WHERE user_id=OLD.user_id AND question_id=OLD.question_id; "
            "END;"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS question_library_au AFTER UPDATE ON question_library "
            "BEGIN "
            "DELETE FROM question_library_fts WHERE user_id=OLD.user_id AND question_id=OLD.question_id; "
            "INSERT INTO question_library_fts(user_id,question_id,subject,knowledge_point,hidden,content) "
            "SELECT "
            "NEW.user_id,"
            "NEW.question_id,"
            "COALESCE(NULLIF(NEW.subject,''), NULLIF(qc.subject,''), ''),"
            "COALESCE(qc.knowledge_point,''),"
            "COALESCE(NEW.hidden,0),"
            "COALESCE(qc.stem,'') || char(10) || COALESCE(qc.answer,'') || char(10) || COALESCE(qc.analysis,'') "
            "FROM question_cache qc WHERE qc.question_id = NEW.question_id; "
            "END;"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS question_cache_au_question_library_fts AFTER UPDATE ON question_cache "
            "BEGIN "
            "DELETE FROM question_library_fts WHERE question_id=OLD.question_id; "
            "INSERT INTO question_library_fts(user_id,question_id,subject,knowledge_point,hidden,content) "
            "SELECT "
            "ql.user_id,"
            "ql.question_id,"
            "COALESCE(NULLIF(ql.subject,''), NULLIF(NEW.subject,''), ''),"
            "COALESCE(NEW.knowledge_point,''),"
            "COALESCE(ql.hidden,0),"
            "COALESCE(NEW.stem,'') || char(10) || COALESCE(NEW.answer,'') || char(10) || COALESCE(NEW.analysis,'') "
            "FROM question_library ql WHERE ql.question_id = NEW.question_id; "
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
            except SQLAlchemyError:
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
        if not _fts_has_any("question_library_fts"):
            conn.exec_driver_sql(
                "INSERT INTO question_library_fts(user_id,question_id,subject,knowledge_point,hidden,content) "
                "SELECT "
                "ql.user_id,"
                "ql.question_id,"
                "COALESCE(NULLIF(ql.subject,''), NULLIF(qc.subject,''), ''),"
                "COALESCE(qc.knowledge_point,''),"
                "COALESCE(ql.hidden,0),"
                "COALESCE(qc.stem,'') || char(10) || COALESCE(qc.answer,'') || char(10) || COALESCE(qc.analysis,'') "
                "FROM question_library ql JOIN question_cache qc ON qc.question_id=ql.question_id"
            )
        if not _fts_has_any("paper_questions_fts"):
            conn.exec_driver_sql(
                "INSERT OR REPLACE INTO paper_questions_fts(rowid,user_id,paper_id,question_id,paper_name,knowledge_point,content) "
                "SELECT pq.id, p.user_id, pq.paper_id, pq.question_id, p.paper_name, pq.knowledge_point, "
                "COALESCE(pq.knowledge_point,'') || char(10) || COALESCE(pq.stem,'') || char(10) || COALESCE(pq.analysis,'') "
                "FROM paper_questions pq JOIN papers p ON p.id=pq.paper_id"
            )
        if not _fts_has_any("study_archives_fts"):
            conn.exec_driver_sql(
                "INSERT OR REPLACE INTO study_archives_fts(rowid,user_id,archive_id,subject,topic,requirements,markdown) "
                "SELECT id, user_id, id, subject, topic, requirements, markdown FROM study_archives"
            )

        # One-time guarded resync: conversations may have been renamed before the
        # conversations_title_au trigger existed, leaving stale titles in the FTS
        # index. The `title IS NOT (...)` guard makes this a cheap no-op when in sync.
        try:
            conn.exec_driver_sql(
                "UPDATE messages_fts SET title = "
                "(SELECT c.title FROM conversations c WHERE c.id = messages_fts.conversation_id) "
                "WHERE title IS NOT "
                "(SELECT c.title FROM conversations c WHERE c.id = messages_fts.conversation_id)"
            )
        except SQLAlchemyError:
            logger.warning("fts_title_resync_failed", exc_info=True)
    except SQLAlchemyError:
        return
