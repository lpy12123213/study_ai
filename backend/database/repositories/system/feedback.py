from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import FeedbackReport


def _normalize_user_id(user_id: str) -> str:
    return normalize_user_id(user_id)


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _json_dumps(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return default


def _json_loads(value: str, *, default: Any) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _row_to_dict(row: FeedbackReport) -> dict:
    return {
        "id": int(row.id),
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "context": _json_loads(row.context_json, default={}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


async def create_feedback(
    *,
    user_id: str,
    title: str,
    description: str,
    context: Optional[Dict[str, Any]] = None,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    title = str(title or "").strip() or "反馈"
    description = str(description or "").strip()
    context = context if isinstance(context, dict) else {}

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await create_feedback(user_id=uid, title=title, description=description, context=context, session=session)
            await session.commit()
            return out

    row = FeedbackReport(
        user_id=uid,
        title=title,
        description=description,
        context_json=_json_dumps(context, default="{}"),
        status="received",
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)


async def list_feedback(
    *,
    user_id: str,
    limit: int = 50,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_feedback(user_id=uid, limit=limit, session=session)

    res = await session.execute(
        select(FeedbackReport).where(FeedbackReport.user_id == uid).order_by(FeedbackReport.updated_at.desc()).limit(int(limit or 50))
    )
    rows = res.scalars().all()
    return [_row_to_dict(r) for r in rows]
