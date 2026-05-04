from __future__ import annotations

import json
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.schema import UserItemMeta


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64]


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _json_dumps(value, *, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return default


def _json_loads(value: str, *, default):
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _row_to_dict(row: UserItemMeta) -> dict:
    return {
        "id": int(row.id),
        "user_id": row.user_id,
        "item_type": row.item_type,
        "item_id": row.item_id,
        "starred": bool(int(row.starred or 0)),
        "pinned": bool(int(row.pinned or 0)),
        "tags": _json_loads(row.tags_json, default=[]),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


async def upsert_item_meta(
    *,
    user_id: str,
    item_type: str,
    item_id: str,
    starred: Optional[bool] = None,
    pinned: Optional[bool] = None,
    tags: Optional[List[str]] = None,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    itype = str(item_type or "").strip()
    iid = str(item_id or "").strip()
    if not itype or not iid:
        raise ValueError("missing_item_ref")

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await upsert_item_meta(
                user_id=uid,
                item_type=itype,
                item_id=iid,
                starred=starred,
                pinned=pinned,
                tags=tags,
                session=session,
            )
            await session.commit()
            return out

    res = await session.execute(
        select(UserItemMeta).where(
            UserItemMeta.user_id == uid,
            UserItemMeta.item_type == itype,
            UserItemMeta.item_id == iid,
        )
    )
    row = res.scalar_one_or_none()
    if row:
        if starred is not None:
            row.starred = 1 if starred else 0
        if pinned is not None:
            row.pinned = 1 if pinned else 0
        if tags is not None:
            cleaned = [str(t).strip() for t in (tags or []) if str(t).strip()]
            row.tags_json = _json_dumps(cleaned, default="[]")
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return _row_to_dict(row)

    cleaned = [str(t).strip() for t in (tags or []) if str(t).strip()]
    row = UserItemMeta(
        user_id=uid,
        item_type=itype,
        item_id=iid,
        starred=1 if starred else 0,
        pinned=1 if pinned else 0,
        tags_json=_json_dumps(cleaned, default="[]"),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)


async def get_item_meta(
    *,
    user_id: str,
    item_type: str,
    item_id: str,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    itype = str(item_type or "").strip()
    iid = str(item_id or "").strip()
    if not itype or not iid:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_item_meta(user_id=uid, item_type=itype, item_id=iid, session=session)

    res = await session.execute(
        select(UserItemMeta).where(
            UserItemMeta.user_id == uid,
            UserItemMeta.item_type == itype,
            UserItemMeta.item_id == iid,
        )
    )
    row = res.scalar_one_or_none()
    return _row_to_dict(row) if row else None


async def list_item_meta(
    *,
    user_id: str,
    item_type: Optional[str] = None,
    starred: Optional[bool] = None,
    pinned: Optional[bool] = None,
    tag: Optional[str] = None,
    limit: int = 200,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_item_meta(
                user_id=uid,
                item_type=item_type,
                starred=starred,
                pinned=pinned,
                tag=tag,
                limit=limit,
                session=session,
            )

    where = [UserItemMeta.user_id == uid]
    if item_type:
        where.append(UserItemMeta.item_type == str(item_type).strip())
    if starred is not None:
        where.append(UserItemMeta.starred == (1 if starred else 0))
    if pinned is not None:
        where.append(UserItemMeta.pinned == (1 if pinned else 0))

    stmt = select(UserItemMeta).where(and_(*where)).order_by(UserItemMeta.updated_at.desc()).limit(int(limit or 200))
    res = await session.execute(stmt)
    rows = res.scalars().all()

    out = [_row_to_dict(r) for r in rows]
    if tag:
        t = str(tag).strip()
        if t:
            out = [x for x in out if t in set([str(v).strip() for v in (x.get("tags") or [])])]
    return out
