from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import UserTemplate


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


def _row_to_dict(row: UserTemplate) -> dict:
    return {
        "id": int(row.id),
        "template_type": row.template_type,
        "name": row.name,
        "body": _json_loads(row.body_json, default={}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


async def create_template(
    *,
    user_id: str,
    template_type: str,
    name: str,
    body: Dict[str, Any],
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    ttype = str(template_type or "").strip()
    name = str(name or "").strip() or "模板"
    body = body if isinstance(body, dict) else {}
    if not ttype:
        raise ValueError("missing_template_type")

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await create_template(user_id=uid, template_type=ttype, name=name, body=body, session=session)
            await session.commit()
            return out

    row = UserTemplate(user_id=uid, template_type=ttype, name=name, body_json=_json_dumps(body, default="{}"))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)


async def list_templates(
    *,
    user_id: str,
    template_type: Optional[str] = None,
    limit: int = 200,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_templates(user_id=uid, template_type=template_type, limit=limit, session=session)

    stmt = select(UserTemplate).where(UserTemplate.user_id == uid)
    if template_type:
        stmt = stmt.where(UserTemplate.template_type == str(template_type).strip())
    stmt = stmt.order_by(UserTemplate.updated_at.desc()).limit(int(limit or 200))
    res = await session.execute(stmt)
    rows = res.scalars().all()
    return [_row_to_dict(r) for r in rows]


async def get_template(
    *,
    user_id: str,
    template_id: int,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    tid = int(template_id or 0)
    if tid <= 0:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_template(user_id=uid, template_id=tid, session=session)

    res = await session.execute(select(UserTemplate).where(UserTemplate.id == tid, UserTemplate.user_id == uid).limit(1))
    row = res.scalar_one_or_none()
    return _row_to_dict(row) if row else None


async def update_template(
    *,
    user_id: str,
    template_id: int,
    name: Optional[str] = None,
    template_type: Optional[str] = None,
    body: Optional[Dict[str, Any]] = None,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    tid = int(template_id or 0)
    if tid <= 0:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await update_template(
                user_id=uid,
                template_id=tid,
                name=name,
                template_type=template_type,
                body=body,
                session=session,
            )
            await session.commit()
            return out

    res = await session.execute(select(UserTemplate).where(UserTemplate.id == tid, UserTemplate.user_id == uid).limit(1))
    row = res.scalar_one_or_none()
    if not row:
        return None

    if name is not None:
        row.name = str(name or "").strip()
    if template_type is not None:
        row.template_type = str(template_type or "").strip()
    if body is not None:
        body_dict = body if isinstance(body, dict) else {}
        row.body_json = _json_dumps(body_dict, default="{}")

    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)


async def delete_template(
    *,
    user_id: str,
    template_id: int,
    session: Optional[AsyncSession] = None,
) -> bool:
    uid = _require_user_id(user_id)
    tid = int(template_id or 0)
    if tid <= 0:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await delete_template(user_id=uid, template_id=tid, session=session)
            await session.commit()
            return ok

    res = await session.execute(select(UserTemplate).where(UserTemplate.id == tid, UserTemplate.user_id == uid))
    row = res.scalar_one_or_none()
    if not row:
        return False
    await session.delete(row)
    await session.flush()
    return True
