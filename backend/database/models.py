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

# ruff: noqa: F401
from backend.database.engine import init_db
from backend.database.repositories.annotations import (
    create_annotation,
    list_annotations,
    update_annotation,
)
from backend.database.repositories.blueprints import (
    delete_blueprint,
    get_blueprint,
    list_blueprints,
    save_blueprint,
)
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
    delete_conversation,
    fork_conversation,
    get_conversation,
    get_messages,
    list_conversations,
    update_conversation_title,
)
from backend.database.repositories.feedback import (
    create_feedback,
    list_feedback,
)
from backend.database.repositories.generated_files import (
    get_generated_file,
    list_generated_files,
    upsert_generated_file,
)
from backend.database.repositories.learning_plans import (
    create_learning_plan,
    get_learning_plan,
    list_learning_plans,
    set_learning_plan_item_completed,
)
from backend.database.repositories.papers import (
    add_questions_to_paper,
    delete_paper,
    get_paper,
    list_papers,
    save_paper,
)
from backend.database.repositories.question_cache import (
    get_question_cache,
    list_used_question_ids,
    mark_used_questions,
    upsert_question_cache,
)
from backend.database.repositories.question_library import (
    bulk_delete_question_library_items,
    get_question_library_item,
    list_question_library_items,
    set_hidden,
    set_starred,
    upsert_question_library_items,
)
from backend.database.repositories.search_history import (
    add_search_history,
)
from backend.database.repositories.share_links import (
    create_share_link,
    get_share_link,
    validate_share_link,
)
from backend.database.repositories.study_archives import (
    get_latest_study_archive,
    get_study_archive_by_fingerprint,
    upsert_study_archive,
)
from backend.database.repositories.templates import (
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)
from backend.database.repositories.user_settings import (
    get_user_settings,
    upsert_user_settings,
)
from backend.database.repositories.wrongbook import (
    delete_wrong_question,
    list_wrong_questions,
    upsert_wrong_question,
)
