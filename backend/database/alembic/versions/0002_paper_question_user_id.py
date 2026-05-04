"""add user scope to paper questions

Revision ID: 0002_paper_question_user_id
Revises: 0001_initial
Create Date: 2026-05-04 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_paper_question_user_id"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def _create_index_if_missing(name: str, table_name: str, columns: list[str]) -> None:
    if _index_exists(table_name, name):
        return
    op.create_index(name, table_name, columns)


def upgrade() -> None:
    if not _table_exists("paper_questions"):
        return

    if not _column_exists("paper_questions", "user_id"):
        op.add_column(
            "paper_questions",
            sa.Column("user_id", sa.String(length=64), nullable=False, server_default=""),
        )

    if _table_exists("papers") and _column_exists("papers", "user_id"):
        op.execute(
            "UPDATE paper_questions "
            "SET user_id = COALESCE((SELECT papers.user_id FROM papers WHERE papers.id = paper_questions.paper_id), '') "
            "WHERE user_id IS NULL OR user_id = ''"
        )

    _create_index_if_missing("ix_paper_questions_user_id", "paper_questions", ["user_id"])
    _create_index_if_missing(
        "ix_paper_questions_user_paper_order",
        "paper_questions",
        ["user_id", "paper_id", "question_order"],
    )
    _create_index_if_missing("ix_paper_questions_user_question", "paper_questions", ["user_id", "question_id"])


def downgrade() -> None:
    if not _table_exists("paper_questions"):
        return

    for index_name in (
        "ix_paper_questions_user_question",
        "ix_paper_questions_user_paper_order",
        "ix_paper_questions_user_id",
    ):
        if _index_exists("paper_questions", index_name):
            op.drop_index(index_name, table_name="paper_questions")

    if _column_exists("paper_questions", "user_id"):
        with op.batch_alter_table("paper_questions") as batch:
            batch.drop_column("user_id")
