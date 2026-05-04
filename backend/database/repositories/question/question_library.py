from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.schema import QuestionCache, QuestionLibraryItem

HiddenFilter = Literal["0", "1", "all"]


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64]


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(default)


async def upsert_question_library_items(
    *,
    user_id: str,
    items: List[dict],
    session: Optional[AsyncSession] = None,
) -> int:
    uid = _require_user_id(user_id)
    entries = [x for x in (items or []) if isinstance(x, dict)]
    if not entries:
        return 0

    own = session is None
    if own:
        async with async_session_maker() as session:
            n = await upsert_question_library_items(user_id=uid, items=entries, session=session)
            await session.commit()
            return n

    n = 0
    for it in entries:
        qid = str(it.get("question_id") or "").strip()
        if not qid:
            continue

        result = await session.execute(
            select(QuestionLibraryItem).where(
                QuestionLibraryItem.user_id == uid,
                QuestionLibraryItem.question_id == qid,
            )
        )
        row = result.scalar_one_or_none() or QuestionLibraryItem(user_id=uid, question_id=qid)

        subj = str(it.get("subject") or "").strip()
        if subj:
            row.subject = subj
        origin = str(it.get("origin") or "").strip()
        if origin:
            row.origin = origin
        if "hidden" in it:
            row.hidden = 1 if bool(it.get("hidden")) else 0
        if "starred" in it:
            row.starred = 1 if bool(it.get("starred")) else 0

        if "ai_score" in it:
            try:
                row.ai_score = int(it.get("ai_score")) if it.get("ai_score") is not None else None
            except (TypeError, ValueError):
                row.ai_score = None
        if "ai_verdict" in it:
            row.ai_verdict = str(it.get("ai_verdict") or "").strip()
        if "ai_dimensions_json" in it:
            row.ai_dimensions_json = str(it.get("ai_dimensions_json") or "").strip()
        if "ai_summary" in it:
            row.ai_summary = str(it.get("ai_summary") or "").strip()

        session.add(row)
        n += 1

    await session.flush()
    return n


async def list_question_library_items(
    *,
    user_id: str,
    subject: str = "",
    origin: str = "",
    hidden: HiddenFilter = "0",
    q: str = "",
    min_score: Optional[int] = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    include_total: bool = True,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    subj = str(subject or "").strip()
    origin_v = str(origin or "").strip()
    qv = str(q or "").strip()
    lim = max(1, min(_as_int(limit, 50), 200))
    off = max(0, _as_int(offset, 0))

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_question_library_items(
                user_id=uid,
                subject=subject,
                origin=origin,
                hidden=hidden,
                q=q,
                min_score=min_score,
                sort=sort,
                order=order,
                limit=limit,
                offset=offset,
                include_total=include_total,
                session=session,
            )

    where = [QuestionLibraryItem.user_id == uid]
    if subj:
        where.append(QuestionLibraryItem.subject == subj)
    if origin_v:
        where.append(QuestionLibraryItem.origin == origin_v)
    if hidden in {"0", "1"}:
        where.append(QuestionLibraryItem.hidden == (1 if hidden == "1" else 0))
    if min_score is not None:
        where.append(QuestionLibraryItem.ai_score >= int(min_score))

    q_filter = None
    if qv:
        like = f"%{qv}%"
        q_filter = or_(QuestionCache.stem.like(like), QuestionLibraryItem.question_id.like(like))

    stmt = (
        select(
            QuestionLibraryItem.question_id,
            QuestionLibraryItem.subject,
            QuestionLibraryItem.origin,
            QuestionLibraryItem.hidden,
            QuestionLibraryItem.starred,
            QuestionLibraryItem.ai_score,
            QuestionLibraryItem.ai_verdict,
            QuestionLibraryItem.ai_summary,
            QuestionLibraryItem.updated_at,
            QuestionCache.stem,
            QuestionCache.question_type,
            QuestionCache.difficulty,
            QuestionCache.difficulty_value,
            QuestionCache.knowledge_point,
            QuestionCache.knowledge_points_json,
            QuestionCache.source_url,
            QuestionCache.quality_score,
            QuestionCache.source,
            QuestionCache.date,
            func.length(func.trim(func.coalesce(QuestionCache.answer, ""))),
            func.length(func.trim(func.coalesce(QuestionCache.analysis, ""))),
        )
        .select_from(QuestionLibraryItem)
        .join(QuestionCache, QuestionCache.question_id == QuestionLibraryItem.question_id, isouter=True)
        .where(*where)
    )
    if q_filter is not None:
        stmt = stmt.where(q_filter)

    sort_key = sort.strip().lower()
    order_key = order.strip().lower()
    col = QuestionLibraryItem.updated_at if sort_key != "ai_score" else QuestionLibraryItem.ai_score
    tie_breaker = QuestionLibraryItem.question_id.asc() if order_key == "asc" else QuestionLibraryItem.question_id.desc()
    stmt = stmt.order_by(desc(col) if order_key != "asc" else col.asc(), tie_breaker)

    total: Optional[int] = None
    if include_total:
        if q_filter is not None:
            total_stmt = (
                select(func.count())
                .select_from(QuestionLibraryItem)
                .join(QuestionCache, QuestionCache.question_id == QuestionLibraryItem.question_id, isouter=True)
                .where(*where, q_filter)
            )
        else:
            total_stmt = select(func.count()).select_from(QuestionLibraryItem).where(*where)
        total = int((await session.execute(total_stmt)).scalar() or 0)

    rows = (await session.execute(stmt.limit(lim).offset(off))).all()

    items: List[Dict[str, Any]] = []
    for r in rows:
        has_answer = int(r[19] or 0) > 0
        has_analysis = int(r[20] or 0) > 0
        items.append(
            {
                "question_id": r[0],
                "subject": r[1] or "",
                "origin": r[2] or "",
                "hidden": bool(r[3]),
                "starred": bool(r[4]),
                "ai_score": r[5],
                "ai_verdict": r[6] or "",
                "ai_summary": r[7] or "",
                "updated_at": r[8].isoformat() if r[8] else "",
                "stem": (r[9] or ""),
                "question_type": r[10] or "",
                "difficulty": r[11] or "",
                "difficulty_value": r[12],
                "knowledge_point": r[13] or "",
                "knowledge_points_json": r[14] or "",
                "source_url": r[15] or "",
                "quality_score": int(r[16] or 0),
                "source": r[17] or "",
                "date": r[18] or "",
                "has_answer": has_answer,
                "has_analysis": has_analysis,
            }
        )

    return {"total": total, "include_total": bool(include_total), "items": items, "limit": lim, "offset": off}


async def bulk_delete_question_library_items(
    *,
    user_id: str,
    question_ids: List[str],
    session: Optional[AsyncSession] = None,
) -> int:
    uid = _require_user_id(user_id)
    ids = [str(x or "").strip() for x in (question_ids or []) if str(x or "").strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return 0

    own = session is None
    if own:
        async with async_session_maker() as session:
            n = await bulk_delete_question_library_items(user_id=uid, question_ids=ids, session=session)
            await session.commit()
            return n

    stmt = delete(QuestionLibraryItem).where(
        QuestionLibraryItem.user_id == uid, QuestionLibraryItem.question_id.in_(ids)
    )
    result = await session.execute(stmt)
    await session.flush()
    try:
        return int(getattr(result, "rowcount", 0) or 0)
    except (TypeError, ValueError):
        return 0


async def set_hidden(
    *,
    user_id: str,
    question_id: str,
    hidden: bool,
    session: Optional[AsyncSession] = None,
) -> bool:
    uid = _require_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await set_hidden(user_id=uid, question_id=qid, hidden=hidden, session=session)
            await session.commit()
            return ok

    result = await session.execute(
        select(QuestionLibraryItem).where(
            QuestionLibraryItem.user_id == uid,
            QuestionLibraryItem.question_id == qid,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    row.hidden = 1 if hidden else 0
    session.add(row)
    await session.flush()
    return True


async def set_starred(
    *,
    user_id: str,
    question_id: str,
    starred: bool,
    session: Optional[AsyncSession] = None,
) -> bool:
    uid = _require_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await set_starred(user_id=uid, question_id=qid, starred=starred, session=session)
            await session.commit()
            return ok

    result = await session.execute(
        select(QuestionLibraryItem).where(
            QuestionLibraryItem.user_id == uid,
            QuestionLibraryItem.question_id == qid,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    row.starred = 1 if starred else 0
    session.add(row)
    await session.flush()
    return True


async def get_question_library_item(
    *,
    user_id: str,
    question_id: str,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_question_library_item(user_id=uid, question_id=qid, session=session)

    result = await session.execute(
        select(QuestionLibraryItem).where(
            QuestionLibraryItem.user_id == uid,
            QuestionLibraryItem.question_id == qid,
        )
    )
    row = result.scalar_one_or_none()

    if not row:
        return None

    return {
        "question_id": row.question_id,
        "subject": row.subject or "",
        "origin": row.origin or "",
        "hidden": bool(row.hidden),
        "starred": bool(getattr(row, "starred", 0)),
        "ai_score": row.ai_score,
        "ai_verdict": row.ai_verdict or "",
        "ai_dimensions_json": row.ai_dimensions_json or "",
        "ai_summary": row.ai_summary or "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


async def list_unscored_question_ids(
    *,
    user_id: str,
    subject: str = "",
    limit: int = 50,
    session: Optional[AsyncSession] = None,
) -> List[str]:
    uid = _require_user_id(user_id)
    subj = str(subject or "").strip()
    lim = max(1, min(_as_int(limit, 50), 500))

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_unscored_question_ids(user_id=uid, subject=subj, limit=lim, session=session)

    stmt = select(QuestionLibraryItem.question_id).where(
        QuestionLibraryItem.user_id == uid,
        QuestionLibraryItem.origin == "crawled",
        QuestionLibraryItem.ai_score.is_(None),
    )
    if subj:
        stmt = stmt.where(QuestionLibraryItem.subject == subj)
    stmt = stmt.limit(lim)
    rows = (await session.execute(stmt)).scalars().all()
    return [str(x).strip() for x in rows if str(x or "").strip()]
