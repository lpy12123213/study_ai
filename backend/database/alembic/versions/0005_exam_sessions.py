"""Add exam session tables.

Revision ID: 0005_exam_sessions
Revises: 0004_essay_evaluations
Create Date: 2026-06-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_exam_sessions"
down_revision = "0004_essay_evaluations"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def _create_index_if_missing(name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if _index_exists(table_name, name):
        return
    op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    if not _table_exists("exam_sessions"):
        op.create_table(
            "exam_sessions",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("paper_id", sa.Integer(), nullable=False),
            sa.Column("paper_name", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("mode", sa.String(length=20), nullable=False, server_default="untimed"),
            sa.Column("time_limit_minutes", sa.Integer(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="in_progress"),
            sa.Column("total_score", sa.Float(), server_default="0"),
            sa.Column("max_score", sa.Float(), server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"]),
        )

    if not _table_exists("student_answers"):
        op.create_table(
            "student_answers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("question_id", sa.String(length=100), nullable=False),
            sa.Column("question_type", sa.String(length=50), nullable=False, server_default=""),
            sa.Column("question_order", sa.Integer(), server_default="0"),
            sa.Column("selected_options_json", sa.Text(), server_default="[]"),
            sa.Column("fill_blank_text", sa.Text(), server_default=""),
            sa.Column("handwriting_image_path", sa.String(length=500), server_default=""),
            sa.Column("text_answer", sa.Text(), server_default=""),
            sa.Column("is_correct", sa.Integer(), nullable=True),
            sa.Column("score", sa.Float(), server_default="0"),
            sa.Column("max_score", sa.Float(), server_default="0"),
            sa.Column("grading_json", sa.Text(), server_default="{}"),
            sa.Column("auto_saved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["session_id"], ["exam_sessions.id"]),
            sa.UniqueConstraint("session_id", "question_id", name="uq_student_answers_session_question"),
        )

    if not _table_exists("exam_results"):
        op.create_table(
            "exam_results",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.String(length=64), nullable=False, unique=True),
            sa.Column("user_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("total_score", sa.Float(), server_default="0"),
            sa.Column("max_score", sa.Float(), server_default="0"),
            sa.Column("score_ratio", sa.Float(), server_default="0"),
            sa.Column("objective_correct", sa.Integer(), server_default="0"),
            sa.Column("objective_total", sa.Integer(), server_default="0"),
            sa.Column("subjective_score", sa.Float(), server_default="0"),
            sa.Column("subjective_max", sa.Float(), server_default="0"),
            sa.Column("breakdown_json", sa.Text(), server_default="[]"),
            sa.Column("ai_feedback_json", sa.Text(), server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["session_id"], ["exam_sessions.id"]),
        )

    for table, specs in {
        "exam_sessions": [
            ("ix_exam_sessions_id", ["id"], False),
            ("ix_exam_sessions_user_id", ["user_id"], False),
            ("ix_exam_sessions_paper_id", ["paper_id"], False),
            ("ix_exam_sessions_mode", ["mode"], False),
            ("ix_exam_sessions_status", ["status"], False),
            ("ix_exam_sessions_started_at", ["started_at"], False),
            ("ix_exam_sessions_submitted_at", ["submitted_at"], False),
            ("ix_exam_sessions_expires_at", ["expires_at"], False),
            ("ix_exam_sessions_created_at", ["created_at"], False),
            ("ix_exam_sessions_updated_at", ["updated_at"], False),
            ("ix_exam_sessions_user_status", ["user_id", "status"], False),
            ("ix_exam_sessions_user_paper", ["user_id", "paper_id"], False),
        ],
        "student_answers": [
            ("ix_student_answers_id", ["id"], False),
            ("ix_student_answers_session_id", ["session_id"], False),
            ("ix_student_answers_user_id", ["user_id"], False),
            ("ix_student_answers_question_id", ["question_id"], False),
            ("ix_student_answers_auto_saved_at", ["auto_saved_at"], False),
            ("ix_student_answers_created_at", ["created_at"], False),
            ("ix_student_answers_updated_at", ["updated_at"], False),
            ("ix_student_answers_user_session", ["user_id", "session_id"], False),
        ],
        "exam_results": [
            ("ix_exam_results_id", ["id"], False),
            ("ix_exam_results_session_id", ["session_id"], True),
            ("ix_exam_results_user_id", ["user_id"], False),
            ("ix_exam_results_created_at", ["created_at"], False),
            ("ix_exam_results_updated_at", ["updated_at"], False),
            ("ix_exam_results_user_session", ["user_id", "session_id"], False),
        ],
    }.items():
        for name, columns, unique in specs:
            _create_index_if_missing(name, table, columns, unique=unique)


def downgrade() -> None:
    for table in ("exam_results", "student_answers", "exam_sessions"):
        if _table_exists(table):
            op.drop_table(table)
