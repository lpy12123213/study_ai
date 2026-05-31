"""Persist lesson plans + users + revoked JWT in SQL.

Revision ID: 0003_lesson_plans_and_auth
Revises: 0002_paper_question_user_id
Create Date: 2026-05-23 00:00:00

This migration replaces three legacy in-memory + JSON-snapshot stores so the
backend works correctly under multi-worker uvicorn deployments:

- ``lesson_plans``         (was: module-level dict in ``backend.generation.lesson_plan.store``)
- ``auth_users``           (was: ``.local/users.json`` + module dict in ``backend.core.auth``)
- ``auth_revoked_jwt``     (was: ``.local/jwt_revoked.json`` + module dict)

Existing JSON snapshots are loaded best-effort; failures are logged via stderr
and the migration still creates empty tables so a fresh boot is functional.
The bootstrap admin row is created in application code, not here, so the
migration stays idempotent across environments with different ``ADMIN_*`` env.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0003_lesson_plans_and_auth"
down_revision = "0002_paper_question_user_id"
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


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _project_root() -> Path:
    # alembic versions live at backend/database/alembic/versions/<file>.py.
    return Path(__file__).resolve().parents[4]


def _load_json_snapshot(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        obj = json.loads(raw) if raw.strip() else {}
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        sys.stderr.write(f"[alembic 0003] failed to read snapshot {path}\n")
        return {}


def _migrate_lesson_plans(bind) -> None:
    snapshot_path = _project_root() / ".local" / "lesson_plans.json"
    plans = _load_json_snapshot(snapshot_path)
    if not plans:
        return

    rows: list[dict] = []
    for plan_id, plan in plans.items():
        if not isinstance(plan, dict):
            continue
        user_id = str(plan.get("user_id") or "").strip()
        if not user_id:
            # Skip ownerless plans rather than attaching them to a random
            # account. They were unreachable anyway under the previous code.
            continue
        rows.append(
            {
                "id": str(plan_id)[:64],
                "user_id": user_id[:64],
                "title": str(plan.get("title") or "")[:255],
                "subject": str(plan.get("subject") or "")[:100],
                "grade": str(plan.get("grade") or "")[:50],
                "topic": str(plan.get("topic") or "")[:200],
                "duration_minutes": int(plan.get("duration_minutes") or 45),
                "status": str(plan.get("status") or "draft")[:32],
                "objectives_json": json.dumps(plan.get("objectives") or [], ensure_ascii=False),
                "sections_json": json.dumps(plan.get("sections") or [], ensure_ascii=False),
                "created_at": plan.get("created_at") or _utcnow_naive().isoformat(),
                "updated_at": plan.get("updated_at") or _utcnow_naive().isoformat(),
            }
        )

    if not rows:
        return

    bind.execute(
        sa.text(
            "INSERT OR IGNORE INTO lesson_plans "
            "(id, user_id, title, subject, grade, topic, duration_minutes, status, "
            " objectives_json, sections_json, created_at, updated_at) "
            "VALUES (:id, :user_id, :title, :subject, :grade, :topic, :duration_minutes, "
            "        :status, :objectives_json, :sections_json, :created_at, :updated_at)"
        ),
        rows,
    )


def _migrate_auth_users(bind) -> None:
    snapshot_path = _project_root() / ".local" / "users.json"
    users = _load_json_snapshot(snapshot_path)
    if not users:
        return

    rows: list[dict] = []
    for username, user in users.items():
        if not isinstance(user, dict):
            continue
        uid = str(user.get("user_id") or "").strip()
        uname = str(username or user.get("username") or "").strip()
        if not uid or not uname:
            continue
        rows.append(
            {
                "user_id": uid[:64],
                "username": uname[:120],
                "password_hash": str(user.get("password_hash") or "")[:200],
                "role": str(user.get("role") or "user")[:32],
                "token_version": int(user.get("token_version") or 1),
                "created_at": user.get("created_at") or _utcnow_naive().isoformat(),
                "updated_at": user.get("updated_at") or user.get("created_at") or _utcnow_naive().isoformat(),
            }
        )

    if not rows:
        return

    bind.execute(
        sa.text(
            "INSERT OR IGNORE INTO auth_users "
            "(user_id, username, password_hash, role, token_version, created_at, updated_at) "
            "VALUES (:user_id, :username, :password_hash, :role, :token_version, :created_at, :updated_at)"
        ),
        rows,
    )


def _migrate_revoked_tokens(bind) -> None:
    snapshot_path = _project_root() / ".local" / "jwt_revoked.json"
    tokens = _load_json_snapshot(snapshot_path)
    if not tokens:
        return

    rows: list[dict] = []
    for jti, exp_ts in tokens.items():
        if not isinstance(jti, str) or not jti.strip():
            continue
        try:
            exp_int = int(exp_ts)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "jti": jti.strip()[:64],
                "exp_ts": exp_int,
                "revoked_at": _utcnow_naive().isoformat(),
            }
        )

    if not rows:
        return

    bind.execute(
        sa.text(
            "INSERT OR IGNORE INTO auth_revoked_jwt (jti, exp_ts, revoked_at) "
            "VALUES (:jti, :exp_ts, :revoked_at)"
        ),
        rows,
    )


def upgrade() -> None:
    if not _table_exists("lesson_plans"):
        op.create_table(
            "lesson_plans",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("subject", sa.String(length=100), server_default=""),
            sa.Column("grade", sa.String(length=50), server_default=""),
            sa.Column("topic", sa.String(length=200), server_default=""),
            sa.Column("duration_minutes", sa.Integer(), server_default="45"),
            sa.Column("status", sa.String(length=32), server_default="draft"),
            sa.Column("objectives_json", sa.Text(), server_default="[]"),
            sa.Column("sections_json", sa.Text(), server_default="[]"),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )
    _create_index_if_missing("ix_lesson_plans_id", "lesson_plans", ["id"])
    _create_index_if_missing("ix_lesson_plans_user_id", "lesson_plans", ["user_id"])
    _create_index_if_missing("ix_lesson_plans_subject", "lesson_plans", ["subject"])
    _create_index_if_missing("ix_lesson_plans_status", "lesson_plans", ["status"])
    _create_index_if_missing("ix_lesson_plans_created_at", "lesson_plans", ["created_at"])
    _create_index_if_missing("ix_lesson_plans_updated_at", "lesson_plans", ["updated_at"])
    _create_index_if_missing("ix_lesson_plans_user_updated", "lesson_plans", ["user_id", "updated_at"])

    if not _table_exists("auth_users"):
        op.create_table(
            "auth_users",
            sa.Column("user_id", sa.String(length=64), primary_key=True),
            sa.Column("username", sa.String(length=120), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="user"),
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )
    _create_index_if_missing("ix_auth_users_user_id", "auth_users", ["user_id"])
    _create_index_if_missing("ix_auth_users_username", "auth_users", ["username"], unique=True)
    _create_index_if_missing("ix_auth_users_role", "auth_users", ["role"])
    _create_index_if_missing("ix_auth_users_created_at", "auth_users", ["created_at"])
    _create_index_if_missing("ix_auth_users_updated_at", "auth_users", ["updated_at"])

    if not _table_exists("auth_revoked_jwt"):
        op.create_table(
            "auth_revoked_jwt",
            sa.Column("jti", sa.String(length=64), primary_key=True),
            sa.Column("exp_ts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("revoked_at", sa.DateTime()),
        )
    _create_index_if_missing("ix_auth_revoked_jwt_exp_ts", "auth_revoked_jwt", ["exp_ts"])
    _create_index_if_missing("ix_auth_revoked_jwt_revoked_at", "auth_revoked_jwt", ["revoked_at"])

    bind = op.get_bind()
    _migrate_lesson_plans(bind)
    _migrate_auth_users(bind)
    _migrate_revoked_tokens(bind)


def downgrade() -> None:
    for index in (
        "ix_lesson_plans_user_updated",
        "ix_lesson_plans_updated_at",
        "ix_lesson_plans_created_at",
        "ix_lesson_plans_status",
        "ix_lesson_plans_subject",
        "ix_lesson_plans_user_id",
        "ix_lesson_plans_id",
    ):
        if _table_exists("lesson_plans") and _index_exists("lesson_plans", index):
            op.drop_index(index, table_name="lesson_plans")
    if _table_exists("lesson_plans"):
        op.drop_table("lesson_plans")

    for index in (
        "ix_auth_users_updated_at",
        "ix_auth_users_created_at",
        "ix_auth_users_role",
        "ix_auth_users_username",
        "ix_auth_users_user_id",
    ):
        if _table_exists("auth_users") and _index_exists("auth_users", index):
            op.drop_index(index, table_name="auth_users")
    if _table_exists("auth_users"):
        op.drop_table("auth_users")

    for index in (
        "ix_auth_revoked_jwt_revoked_at",
        "ix_auth_revoked_jwt_exp_ts",
    ):
        if _table_exists("auth_revoked_jwt") and _index_exists("auth_revoked_jwt", index):
            op.drop_index(index, table_name="auth_revoked_jwt")
    if _table_exists("auth_revoked_jwt"):
        op.drop_table("auth_revoked_jwt")
