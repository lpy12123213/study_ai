from __future__ import annotations

import json
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import Blueprint


def _normalize_user_id(user_id: str) -> str:
    return normalize_user_id(user_id)


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


async def list_blueprints(
    *,
    user_id: str,
    limit: int = 100,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_blueprints(user_id=uid, limit=limit, session=session)

    result = await session.execute(
        select(Blueprint).where(Blueprint.user_id == uid).order_by(Blueprint.updated_at.desc()).limit(int(limit or 100))
    )
    items = result.scalars().all()

    out: List[dict] = []
    for bp in items:
        try:
            slots = json.loads(bp.slots_json or "[]")
            if not isinstance(slots, list):
                slots = []
        except (json.JSONDecodeError, TypeError):
            slots = []
        out.append(
            {
                "id": bp.id,
                "name": bp.name,
                "subject": bp.subject,
                "topic": bp.topic,
                "slots": slots,
                "createdAt": bp.created_at.isoformat() if bp.created_at else "",
                "updatedAt": bp.updated_at.isoformat() if bp.updated_at else "",
            }
        )
    return out


async def get_blueprint(
    *,
    user_id: str,
    blueprint_id: str,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    bid = (blueprint_id or "").strip()
    if not bid:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_blueprint(user_id=uid, blueprint_id=bid, session=session)

    result = await session.execute(select(Blueprint).where(Blueprint.id == bid, Blueprint.user_id == uid))
    bp = result.scalar_one_or_none()
    if not bp:
        return None

    try:
        slots = json.loads(bp.slots_json or "[]")
        if not isinstance(slots, list):
            slots = []
    except (json.JSONDecodeError, TypeError):
        slots = []

    return {
        "id": bp.id,
        "name": bp.name,
        "subject": bp.subject,
        "topic": bp.topic,
        "slots": slots,
        "createdAt": bp.created_at.isoformat() if bp.created_at else "",
        "updatedAt": bp.updated_at.isoformat() if bp.updated_at else "",
    }


async def save_blueprint(
    *,
    user_id: str,
    blueprint_id: str,
    name: str,
    subject: str,
    topic: str,
    slots: List[dict],
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    bid = (blueprint_id or "").strip() or uuid.uuid4().hex
    name = (name or "").strip()
    subject = (subject or "").strip()
    topic = (topic or "").strip()

    try:
        slots_json = json.dumps(slots or [], ensure_ascii=False)
    except (TypeError, ValueError):
        slots_json = "[]"

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await save_blueprint(
                user_id=uid,
                blueprint_id=bid,
                name=name,
                subject=subject,
                topic=topic,
                slots=slots,
                session=session,
            )
            await session.commit()
            return out

    res = await session.execute(select(Blueprint).where(Blueprint.id == bid, Blueprint.user_id == uid))
    existing = res.scalar_one_or_none()

    if existing:
        existing.name = name or existing.name
        existing.subject = subject or existing.subject
        existing.topic = topic
        existing.slots_json = slots_json
        session.add(existing)
        await session.flush()
        await session.refresh(existing)
        out = await get_blueprint(user_id=uid, blueprint_id=existing.id, session=session)
        return out or {"id": existing.id}

    bp = Blueprint(
        id=bid,
        user_id=uid,
        name=name,
        subject=subject,
        topic=topic,
        slots_json=slots_json,
    )
    session.add(bp)
    await session.flush()
    await session.refresh(bp)
    out = await get_blueprint(user_id=uid, blueprint_id=bp.id, session=session)
    return out or {"id": bp.id}


async def delete_blueprint(
    *,
    user_id: str,
    blueprint_id: str,
    session: Optional[AsyncSession] = None,
) -> bool:
    uid = _require_user_id(user_id)
    bid = (blueprint_id or "").strip()
    if not bid:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await delete_blueprint(user_id=uid, blueprint_id=bid, session=session)
            await session.commit()
            return ok

    result = await session.execute(select(Blueprint).where(Blueprint.id == bid, Blueprint.user_id == uid))
    bp = result.scalar_one_or_none()
    if not bp:
        return False
    await session.delete(bp)
    await session.flush()
    return True
