"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-03-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_papers_id", "papers", ["id"])

    op.create_table(
        "paper_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("question_id", sa.String(length=50), nullable=False),
        sa.Column("question_order", sa.Integer(), nullable=True),
        sa.Column("question_type", sa.String(length=50), nullable=True),
        sa.Column("difficulty", sa.String(length=20), nullable=True),
        sa.Column("knowledge_point", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("stem", sa.Text(), nullable=True),
        sa.Column("stem_fingerprint", sa.String(length=32), nullable=True),
        sa.Column("difficulty_value", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("quality_flags", sa.Text(), nullable=True),
        sa.Column("knowledge_points_json", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=200), nullable=True),
        sa.Column("date", sa.String(length=50), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("analysis", sa.Text(), nullable=True),
    )
    op.create_index("ix_paper_questions_id", "paper_questions", ["id"])

    op.create_table(
        "blueprints",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=100), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("slots_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_blueprints_id", "blueprints", ["id"])
    op.create_index("ix_blueprints_user_id", "blueprints", ["user_id"])

    op.create_table(
        "search_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_type", sa.String(length=50), nullable=True),
        sa.Column("search_query", sa.String(length=500), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_search_history_id", "search_history", ["id"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_conversations_id", "conversations", ["id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_calls", sa.Text(), nullable=True),
        sa.Column("tool_call_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_messages_id", "messages", ["id"])

    op.create_table(
        "canvas_boards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=100), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("snapshot", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_canvas_boards_id", "canvas_boards", ["id"])

    op.create_table(
        "canvas_board_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("board_id", sa.Integer(), sa.ForeignKey("canvas_boards.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_canvas_board_versions_id", "canvas_board_versions", ["id"])

    op.create_table(
        "used_questions",
        sa.Column("question_id", sa.String(length=50), primary_key=True),
        sa.Column("subject", sa.String(length=100), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "question_cache",
        sa.Column("question_id", sa.String(length=50), primary_key=True),
        sa.Column("subject", sa.String(length=100), nullable=True),
        sa.Column("question_type", sa.String(length=50), nullable=True),
        sa.Column("difficulty", sa.String(length=20), nullable=True),
        sa.Column("knowledge_point", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("stem", sa.Text(), nullable=True),
        sa.Column("stem_fingerprint", sa.String(length=32), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("analysis", sa.Text(), nullable=True),
        sa.Column("difficulty_value", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("quality_flags", sa.Text(), nullable=True),
        sa.Column("knowledge_points_json", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=200), nullable=True),
        sa.Column("date", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "study_archives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("subject", sa.String(length=100), nullable=True),
        sa.Column("topic", sa.String(length=200), nullable=True),
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("preset", sa.String(length=32), nullable=True),
        sa.Column("requirements", sa.Text(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("sections_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_study_archives_id", "study_archives", ["id"])
    op.create_index("ix_study_archives_fingerprint", "study_archives", ["fingerprint"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_study_archives_fingerprint", table_name="study_archives")
    op.drop_index("ix_study_archives_id", table_name="study_archives")
    op.drop_table("study_archives")
    op.drop_table("question_cache")
    op.drop_table("used_questions")
    op.drop_index("ix_canvas_board_versions_id", table_name="canvas_board_versions")
    op.drop_table("canvas_board_versions")
    op.drop_index("ix_canvas_boards_id", table_name="canvas_boards")
    op.drop_table("canvas_boards")
    op.drop_index("ix_messages_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_search_history_id", table_name="search_history")
    op.drop_table("search_history")
    op.drop_index("ix_blueprints_user_id", table_name="blueprints")
    op.drop_index("ix_blueprints_id", table_name="blueprints")
    op.drop_table("blueprints")
    op.drop_index("ix_paper_questions_id", table_name="paper_questions")
    op.drop_table("paper_questions")
    op.drop_index("ix_papers_id", table_name="papers")
    op.drop_table("papers")
