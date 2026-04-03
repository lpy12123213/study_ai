from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.schema import WrongQuestion


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
    except Exception:
        return default


def _json_loads(value: str, *, default: Any) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _row_to_dict(row: WrongQuestion) -> dict:
    return {
        "id": int(row.id),
        "question_id": row.question_id,
        "subject": row.subject,
        "knowledge_point": row.knowledge_point,
        "mastery": int(row.mastery or 0),
        "note": row.note,
        "tags": _json_loads(row.tags_json, default=[]),
        "source_ref": _json_loads(row.source_ref_json, default={}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


async def upsert_wrong_question(
    *,
    user_id: str,
    question_id: str,
    subject: str = "",
    knowledge_point: str = "",
    mastery: Optional[int] = None,
    note: str = "",
    tags: Optional[List[str]] = None,
    source_ref: Optional[Dict[str, Any]] = None,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        raise ValueError("missing_question_id")

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await upsert_wrong_question(
                user_id=uid,
                question_id=qid,
                subject=subject,
                knowledge_point=knowledge_point,
                mastery=mastery,
                note=note,
                tags=tags,
                source_ref=source_ref,
                session=session,
            )
            await session.commit()
            return out

    res = await session.execute(select(WrongQuestion).where(WrongQuestion.user_id == uid, WrongQuestion.question_id == qid))
    row = res.scalar_one_or_none()
    if row:
        row.subject = str(subject or row.subject or "").strip()
        row.knowledge_point = str(knowledge_point or row.knowledge_point or "").strip()
        if mastery is not None:
            try:
                row.mastery = int(mastery)
            except Exception:
                row.mastery = int(row.mastery or 0)
        if note is not None:
            row.note = str(note or "").strip()
        if tags is not None:
            cleaned_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
            row.tags_json = _json_dumps(cleaned_tags, default="[]")
        if source_ref is not None:
            row.source_ref_json = _json_dumps(source_ref, default="{}")
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return _row_to_dict(row)

    cleaned_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
    row = WrongQuestion(
        user_id=uid,
        question_id=qid,
        subject=str(subject or "").strip(),
        knowledge_point=str(knowledge_point or "").strip(),
        mastery=int(mastery or 0) if mastery is not None else 0,
        note=str(note or "").strip(),
        tags_json=_json_dumps(cleaned_tags, default="[]"),
        source_ref_json=_json_dumps(source_ref or {}, default="{}"),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)


async def delete_wrong_question(
    *,
    user_id: str,
    question_id: str,
    session: Optional[AsyncSession] = None,
) -> bool:
    uid = _require_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await delete_wrong_question(user_id=uid, question_id=qid, session=session)
            await session.commit()
            return ok

    res = await session.execute(select(WrongQuestion).where(WrongQuestion.user_id == uid, WrongQuestion.question_id == qid))
    row = res.scalar_one_or_none()
    if not row:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def list_wrong_questions(
    *,
    user_id: str,
    subject: Optional[str] = None,
    knowledge_point: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_wrong_questions(
                user_id=uid,
                subject=subject,
                knowledge_point=knowledge_point,
                q=q,
                limit=limit,
                session=session,
            )

    where = [WrongQuestion.user_id == uid]
    if subject:
        where.append(WrongQuestion.subject == str(subject).strip())
    if knowledge_point:
        where.append(WrongQuestion.knowledge_point == str(knowledge_point).strip())

    stmt = select(WrongQuestion).where(and_(*where)).order_by(WrongQuestion.updated_at.desc()).limit(int(limit or 200))
    res = await session.execute(stmt)
    rows = res.scalars().all()
    out = [_row_to_dict(r) for r in rows]
    if q:
        needle = str(q).strip().lower()
        if needle:
            out = [x for x in out if needle in str(x.get("question_id") or "").lower() or needle in str(x.get("note") or "").lower()]
    return out
