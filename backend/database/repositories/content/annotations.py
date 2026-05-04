from __future__ import annotations

import json
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.schema import Annotation


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


def _row_to_dict(row: Annotation) -> dict:
    return {
        "id": int(row.id),
        "item_type": row.item_type,
        "item_id": row.item_id,
        "anchor": row.anchor,
        "snippet": row.snippet,
        "content": row.content,
        "tags": _json_loads(row.tags_json, default=[]),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


async def create_annotation(
    *,
    user_id: str,
    item_type: str,
    item_id: str,
    anchor: str = "",
    snippet: str = "",
    content: str = "",
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
            out = await create_annotation(
                user_id=uid,
                item_type=itype,
                item_id=iid,
                anchor=anchor,
                snippet=snippet,
                content=content,
                tags=tags,
                session=session,
            )
            await session.commit()
            return out

    cleaned_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
    row = Annotation(
        user_id=uid,
        item_type=itype,
        item_id=iid,
        anchor=str(anchor or "").strip()[:120],
        snippet=str(snippet or "").strip()[:300],
        content=str(content or "").strip(),
        tags_json=_json_dumps(cleaned_tags, default="[]"),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)


async def list_annotations(
    *,
    user_id: str,
    item_type: Optional[str] = None,
    item_id: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 200,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_annotations(
                user_id=uid,
                item_type=item_type,
                item_id=item_id,
                tag=tag,
                limit=limit,
                session=session,
            )

    where = [Annotation.user_id == uid]
    if item_type:
        where.append(Annotation.item_type == str(item_type).strip())
    if item_id:
        where.append(Annotation.item_id == str(item_id).strip())

    stmt = select(Annotation).where(and_(*where)).order_by(Annotation.updated_at.desc()).limit(int(limit or 200))
    res = await session.execute(stmt)
    rows = res.scalars().all()
    out = [_row_to_dict(r) for r in rows]
    if tag:
        t = str(tag).strip()
        if t:
            out = [x for x in out if t in set([str(v).strip() for v in (x.get("tags") or [])])]
    return out


async def update_annotation(
    *,
    user_id: str,
    annotation_id: int,
    content: Optional[str] = None,
    tags: Optional[List[str]] = None,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    aid = int(annotation_id or 0)
    if aid <= 0:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await update_annotation(user_id=uid, annotation_id=aid, content=content, tags=tags, session=session)
            await session.commit()
            return out

    res = await session.execute(select(Annotation).where(and_(Annotation.id == aid, Annotation.user_id == uid)).limit(1))
    row = res.scalar_one_or_none()
    if not row:
        return None

    if content is not None:
        row.content = str(content or "").strip()

    if tags is not None:
        cleaned_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        row.tags_json = _json_dumps(cleaned_tags, default="[]")

    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)
