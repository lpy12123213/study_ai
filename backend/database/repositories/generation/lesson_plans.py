"""Async CRUD for lesson plans, owner-scoped at every entry point.

Replaces the legacy module-level dict + JSON snapshot in
``backend.generation.lesson_plan.store``. Every read/write filters by
``user_id``; helpers that look up a plan by id without an owner are
deliberately not provided.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.time_utils import utcnow
from backend.database.engine import async_session_maker
from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import LessonPlanRecord


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #


def _normalize_user_id(user_id: str) -> str:
    return normalize_user_id(user_id)


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _safe_loads(raw: str, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _row_to_dict(row: LessonPlanRecord) -> Dict[str, Any]:
    objectives = _safe_loads(row.objectives_json or "[]", [])
    sections = _safe_loads(row.sections_json or "[]", [])
    return {
        "id": str(row.id),
        "user_id": str(row.user_id or ""),
        "title": str(row.title or ""),
        "subject": str(row.subject or ""),
        "grade": str(row.grade or "") or None,
        "topic": str(row.topic or ""),
        "duration_minutes": int(row.duration_minutes or 0),
        "status": str(row.status or "draft"),
        "objectives": objectives if isinstance(objectives, list) else [],
        "sections": sections if isinstance(sections, list) else [],
        "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else None,
        "updated_at": row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else None,
    }


# --------------------------------------------------------------------------- #
# CRUD                                                                         #
# --------------------------------------------------------------------------- #


async def create_lesson_plan(
    *,
    user_id: str,
    title: str,
    subject: str,
    topic: str,
    grade: Optional[str] = None,
    duration_minutes: int = 45,
    objectives: Optional[List[str]] = None,
    plan_id: Optional[str] = None,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    uid = _require_user_id(user_id)

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await create_lesson_plan(
                user_id=uid,
                title=title,
                subject=subject,
                topic=topic,
                grade=grade,
                duration_minutes=duration_minutes,
                objectives=objectives,
                plan_id=plan_id,
                session=session,
            )
            await session.commit()
            return out

    pid = str(plan_id or uuid.uuid4().hex)
    now = utcnow().replace(tzinfo=None)
    objectives_payload = [
        {"description": str(obj or ""), "type": "knowledge"} for obj in (objectives or [])
    ]

    row = LessonPlanRecord(
        id=pid,
        user_id=uid,
        title=str(title or "").strip()[:255] or "未命名教案",
        subject=str(subject or "").strip()[:100],
        grade=str(grade or "").strip()[:50] if grade else "",
        topic=str(topic or "").strip()[:200],
        duration_minutes=int(duration_minutes or 45),
        status="draft",
        objectives_json=json.dumps(objectives_payload, ensure_ascii=False),
        sections_json="[]",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)


async def get_lesson_plan(
    *, plan_id: str, user_id: str, session: Optional[AsyncSession] = None
) -> Optional[Dict[str, Any]]:
    """Fetch a plan by id, scoped to its owner.

    Returns ``None`` when the plan does not exist OR is owned by another user.
    """

    uid = _normalize_user_id(user_id)
    if not uid:
        return None
    pid = str(plan_id or "").strip()
    if not pid:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_lesson_plan(plan_id=pid, user_id=uid, session=session)

    res = await session.execute(
        select(LessonPlanRecord).where(LessonPlanRecord.id == pid, LessonPlanRecord.user_id == uid)
    )
    row = res.scalar_one_or_none()
    return _row_to_dict(row) if row else None


async def list_lesson_plans(
    *, user_id: str, session: Optional[AsyncSession] = None, limit: int = 200
) -> List[Dict[str, Any]]:
    uid = _normalize_user_id(user_id)
    if not uid:
        return []

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_lesson_plans(user_id=uid, session=session, limit=limit)

    safe_limit = max(1, min(int(limit or 200), 1000))
    stmt = (
        select(LessonPlanRecord)
        .where(LessonPlanRecord.user_id == uid)
        .order_by(LessonPlanRecord.created_at.desc())
        .limit(safe_limit)
    )
    res = await session.execute(stmt)
    return [_row_to_dict(row) for row in res.scalars().all()]


async def update_lesson_plan(
    *,
    plan_id: str,
    user_id: str,
    title: Optional[str] = None,
    objectives: Optional[List[Dict[str, Any]]] = None,
    sections: Optional[List[Dict[str, Any]]] = None,
    status: Optional[str] = None,
    session: Optional[AsyncSession] = None,
) -> Optional[Dict[str, Any]]:
    """Partial update; returns ``None`` if the plan is missing or not owned."""

    uid = _normalize_user_id(user_id)
    if not uid:
        return None
    pid = str(plan_id or "").strip()
    if not pid:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await update_lesson_plan(
                plan_id=pid,
                user_id=uid,
                title=title,
                objectives=objectives,
                sections=sections,
                status=status,
                session=session,
            )
            await session.commit()
            return out

    res = await session.execute(
        select(LessonPlanRecord).where(LessonPlanRecord.id == pid, LessonPlanRecord.user_id == uid)
    )
    row = res.scalar_one_or_none()
    if row is None:
        return None

    if title is not None:
        row.title = str(title)[:255]
    if objectives is not None:
        row.objectives_json = json.dumps(list(objectives), ensure_ascii=False)
    if sections is not None:
        row.sections_json = json.dumps(list(sections), ensure_ascii=False)
    if status is not None:
        row.status = str(status)[:32]
    row.updated_at = utcnow().replace(tzinfo=None)

    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)


async def delete_lesson_plan(
    *, plan_id: str, user_id: str, session: Optional[AsyncSession] = None
) -> bool:
    uid = _normalize_user_id(user_id)
    if not uid:
        return False
    pid = str(plan_id or "").strip()
    if not pid:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await delete_lesson_plan(plan_id=pid, user_id=uid, session=session)
            await session.commit()
            return ok

    res = await session.execute(
        select(LessonPlanRecord).where(LessonPlanRecord.id == pid, LessonPlanRecord.user_id == uid)
    )
    row = res.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    return True
