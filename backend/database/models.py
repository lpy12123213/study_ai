"""
Database compatibility layer.

Historically this project used a single huge `backend/database/models.py` file that
contained:
- SQLAlchemy models
- engine/session setup
- best-effort SQLite schema upgrades
- domain CRUD helpers

To improve maintainability we split it into:
- `backend/database/schema.py`     models
- `backend/database/engine.py`     engine/session/init_db
- `backend/database/repositories/` CRUD helpers

This module keeps the old import paths working.
"""

from __future__ import annotations

from backend.database.base import Base
from backend.database.engine import DATABASE_URL, DB_PATH, async_session_maker, engine, get_session, init_db
from backend.database.schema import (
    Blueprint,
    CanvasBoard,
    CanvasBoardVersion,
    Conversation,
    Message,
    Paper,
    PaperQuestion,
    QuestionCache,
    QuestionLibraryItem,
    SearchHistory,
    StudyArchive,
    UsedQuestion,
)

from backend.database.repositories.blueprints import delete_blueprint, get_blueprint, list_blueprints, save_blueprint
from backend.database.repositories.canvas import (
    create_canvas_board,
    create_canvas_board_version,
    get_canvas_board,
    get_canvas_board_version,
    list_canvas_board_versions,
    list_canvas_boards,
    update_canvas_board,
)
from backend.database.repositories.conversations import (
    add_message,
    create_conversation,
    delete_all_conversations,
    delete_conversation,
    fork_conversation,
    get_conversation,
    get_messages,
    list_conversations,
    update_conversation_title,
)
from backend.database.repositories.papers import add_questions_to_paper, delete_paper, get_paper, list_papers, save_paper
from backend.database.repositories.question_cache import (
    get_question_cache,
    list_used_question_ids,
    mark_used_questions,
    upsert_question_cache,
)
from backend.database.repositories.question_library import (
    get_question_library_item,
    list_question_library_items,
    list_unscored_question_ids,
    set_hidden,
    upsert_question_library_items,
)
from backend.database.repositories.search_history import add_search_history
from backend.database.repositories.study_archives import (
    build_study_archive_fingerprint,
    get_latest_study_archive,
    get_study_archive_by_fingerprint,
    upsert_study_archive,
)
