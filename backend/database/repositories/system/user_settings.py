from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.schema import UserSettings


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64]


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


async def get_user_settings(
    *,
    user_id: str,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_user_settings(user_id=uid, session=session)

    res = await session.execute(select(UserSettings).where(UserSettings.user_id == uid))
    row = res.scalar_one_or_none()
    if not row:
        return {"user_id": uid, "settings": {}}
    return {"user_id": row.user_id, "settings": _json_loads(row.settings_json, default={})}


async def upsert_user_settings(
    *,
    user_id: str,
    settings: Dict[str, Any],
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    payload = settings if isinstance(settings, dict) else {}
    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await upsert_user_settings(user_id=uid, settings=payload, session=session)
            await session.commit()
            return out

    res = await session.execute(select(UserSettings).where(UserSettings.user_id == uid))
    row = res.scalar_one_or_none()
    if row:
        row.settings_json = _json_dumps(payload, default="{}")
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return {"user_id": row.user_id, "settings": _json_loads(row.settings_json, default={})}

    row = UserSettings(user_id=uid, settings_json=_json_dumps(payload, default="{}"))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return {"user_id": row.user_id, "settings": _json_loads(row.settings_json, default={})}
