"""Add isolated Gaokao question provenance records.

Revision ID: 0006_gaokao_question_sources
Revises: 0005_exam_sessions
Create Date: 2026-08-21 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_gaokao_question_sources"
down_revision = "0005_exam_sessions"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_exists("gaokao_question_sources"):
        return

    op.create_table(
        "gaokao_question_sources",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("question_id", sa.String(length=50), nullable=False),
        sa.Column("exam_year", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("paper_name", sa.String(length=200), nullable=False),
        sa.Column("paper_variant", sa.String(length=100), server_default=""),
        sa.Column("question_number", sa.String(length=50), server_default=""),
        sa.Column("source_url", sa.String(length=1000), server_default=""),
        sa.Column("source_note", sa.Text(), server_default=""),
        sa.Column("verified", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id", "question_id"],
            ["question_library.user_id", "question_library.question_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "question_id"),
    )
    op.create_index("ix_gaokao_sources_user_year", "gaokao_question_sources", ["user_id", "exam_year"])
    op.create_index(
        "ix_gaokao_sources_user_region_year",
        "gaokao_question_sources",
        ["user_id", "region", "exam_year"],
    )
    op.create_index("ix_gaokao_sources_user_paper", "gaokao_question_sources", ["user_id", "paper_name"])


def downgrade() -> None:
    if _table_exists("gaokao_question_sources"):
        op.drop_table("gaokao_question_sources")
