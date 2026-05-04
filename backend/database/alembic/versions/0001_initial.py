"""baseline existing Study AI schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-04 00:00:00
"""

from __future__ import annotations

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline for installations that already used Base.metadata.create_all.
    pass


def downgrade() -> None:
    # Do not drop application tables from the baseline revision.
    pass
