from __future__ import annotations

import json
import uuid
from typing import List, Optional

from sqlalchemy import select

from backend.database.engine import async_session_maker
from backend.database.schema import Blueprint


async def list_blueprints(*, user_id: str, limit: int = 100) -> List[dict]:
    uid = (user_id or "").strip() or "anonymous"

    async with async_session_maker() as session:
        result = await session.execute(
            select(Blueprint)
            .where(Blueprint.user_id == uid)
            .order_by(Blueprint.updated_at.desc())
            .limit(int(limit or 100))
        )
        items = result.scalars().all()

        out: List[dict] = []
        for bp in items:
            try:
                slots = json.loads(bp.slots_json or "[]")
                if not isinstance(slots, list):
                    slots = []
            except Exception:
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


async def get_blueprint(*, user_id: str, blueprint_id: str) -> Optional[dict]:
    uid = (user_id or "").strip() or "anonymous"
    bid = (blueprint_id or "").strip()
    if not bid:
        return None

    async with async_session_maker() as session:
        result = await session.execute(select(Blueprint).where(Blueprint.id == bid, Blueprint.user_id == uid))
        bp = result.scalar_one_or_none()
        if not bp:
            return None

        try:
            slots = json.loads(bp.slots_json or "[]")
            if not isinstance(slots, list):
                slots = []
        except Exception:
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
) -> dict:
    uid = (user_id or "").strip() or "anonymous"
    bid = (blueprint_id or "").strip() or uuid.uuid4().hex
    name = (name or "").strip()
    subject = (subject or "").strip()
    topic = (topic or "").strip()

    try:
        slots_json = json.dumps(slots or [], ensure_ascii=False)
    except Exception:
        slots_json = "[]"

    async with async_session_maker() as session:
        existing = None
        res = await session.execute(select(Blueprint).where(Blueprint.id == bid, Blueprint.user_id == uid))
        existing = res.scalar_one_or_none()

        if existing:
            existing.name = name or existing.name
            existing.subject = subject or existing.subject
            existing.topic = topic
            existing.slots_json = slots_json
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
            out = await get_blueprint(user_id=uid, blueprint_id=existing.id)
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
        await session.commit()
        await session.refresh(bp)
        out = await get_blueprint(user_id=uid, blueprint_id=bp.id)
        return out or {"id": bp.id}


async def delete_blueprint(*, user_id: str, blueprint_id: str) -> bool:
    uid = (user_id or "").strip() or "anonymous"
    bid = (blueprint_id or "").strip()
    if not bid:
        return False

    async with async_session_maker() as session:
        result = await session.execute(select(Blueprint).where(Blueprint.id == bid, Blueprint.user_id == uid))
        bp = result.scalar_one_or_none()
        if not bp:
            return False
        await session.delete(bp)
        await session.commit()
        return True

