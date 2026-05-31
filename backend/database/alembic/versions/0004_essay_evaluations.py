"""Add essay_evaluations history table.

Revision ID: 0004_essay_evaluations
Revises: 0003_lesson_plans_and_auth
Create Date: 2026-05-23 00:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_essay_evaluations"
down_revision = "0003_lesson_plans_and_auth"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def _create_index_if_missing(name: str, table_name: str, columns: list[str]) -> None:
    if _index_exists(table_name, name):
        return
    op.create_index(name, table_name, columns)


def upgrade() -> None:
    if not _table_exists("essay_evaluations"):
        op.create_table(
            "essay_evaluations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("subject", sa.String(length=40), server_default="语文"),
            sa.Column("topic", sa.String(length=200), server_default=""),
            sa.Column("essay_type", sa.String(length=32), server_default="argumentative"),
            sa.Column("grade_band", sa.String(length=32), server_default="senior"),
            sa.Column("language", sa.String(length=8), server_default="zh"),
            sa.Column("essay_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("requirements", sa.Text(), server_default=""),
            sa.Column("score_total", sa.Float(), server_default="0"),
            sa.Column("score_max", sa.Float(), server_default="0"),
            sa.Column("grade", sa.String(length=32), server_default=""),
            sa.Column("scores_json", sa.Text(), server_default="[]"),
            sa.Column("feedback_json", sa.Text(), server_default="{}"),
            sa.Column("model", sa.String(length=100), server_default=""),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )

    _create_index_if_missing("ix_essay_evaluations_id", "essay_evaluations", ["id"])
    _create_index_if_missing("ix_essay_evaluations_user_id", "essay_evaluations", ["user_id"])
    _create_index_if_missing("ix_essay_evaluations_subject", "essay_evaluations", ["subject"])
    _create_index_if_missing("ix_essay_evaluations_essay_type", "essay_evaluations", ["essay_type"])
    _create_index_if_missing("ix_essay_evaluations_grade_band", "essay_evaluations", ["grade_band"])
    _create_index_if_missing("ix_essay_evaluations_language", "essay_evaluations", ["language"])
    _create_index_if_missing("ix_essay_evaluations_score_total", "essay_evaluations", ["score_total"])
    _create_index_if_missing("ix_essay_evaluations_created_at", "essay_evaluations", ["created_at"])
    _create_index_if_missing("ix_essay_evaluations_updated_at", "essay_evaluations", ["updated_at"])
    _create_index_if_missing("ix_essay_evaluations_user_created", "essay_evaluations", ["user_id", "created_at"])


def downgrade() -> None:
    if not _table_exists("essay_evaluations"):
        return

    for idx in (
        "ix_essay_evaluations_user_created",
        "ix_essay_evaluations_updated_at",
        "ix_essay_evaluations_created_at",
        "ix_essay_evaluations_score_total",
        "ix_essay_evaluations_language",
        "ix_essay_evaluations_grade_band",
        "ix_essay_evaluations_essay_type",
        "ix_essay_evaluations_subject",
        "ix_essay_evaluations_user_id",
        "ix_essay_evaluations_id",
    ):
        if _index_exists("essay_evaluations", idx):
            op.drop_index(idx, table_name="essay_evaluations")

    op.drop_table("essay_evaluations")
