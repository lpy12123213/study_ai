from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from sqlalchemy import desc, func, or_, select

from backend.database.engine import async_session_maker
from backend.database.schema import QuestionCache, QuestionLibraryItem

HiddenFilter = Literal["0", "1", "all"]


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64] or "1"


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


async def upsert_question_library_items(*, user_id: str, items: List[dict]) -> int:
    uid = _normalize_user_id(user_id)
    entries = [x for x in (items or []) if isinstance(x, dict)]
    if not entries:
        return 0

    async with async_session_maker() as session:
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

            if "ai_score" in it:
                try:
                    row.ai_score = int(it.get("ai_score")) if it.get("ai_score") is not None else None
                except Exception:
                    row.ai_score = None
            if "ai_verdict" in it:
                row.ai_verdict = str(it.get("ai_verdict") or "").strip()
            if "ai_dimensions_json" in it:
                row.ai_dimensions_json = str(it.get("ai_dimensions_json") or "").strip()
            if "ai_summary" in it:
                row.ai_summary = str(it.get("ai_summary") or "").strip()

            session.add(row)
            n += 1
        await session.commit()
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
) -> dict:
    uid = _normalize_user_id(user_id)
    subj = str(subject or "").strip()
    origin_v = str(origin or "").strip()
    qv = str(q or "").strip()
    lim = max(1, min(_as_int(limit, 50), 200))
    off = max(0, _as_int(offset, 0))

    async with async_session_maker() as session:
        stmt = (
            select(
                QuestionLibraryItem.question_id,
                QuestionLibraryItem.subject,
                QuestionLibraryItem.origin,
                QuestionLibraryItem.hidden,
                QuestionLibraryItem.ai_score,
                QuestionLibraryItem.ai_verdict,
                QuestionLibraryItem.ai_summary,
                QuestionLibraryItem.updated_at,
                QuestionCache.stem,
            )
            .select_from(QuestionLibraryItem)
            .join(QuestionCache, QuestionCache.question_id == QuestionLibraryItem.question_id, isouter=True)
            .where(QuestionLibraryItem.user_id == uid)
        )

        if subj:
            stmt = stmt.where(QuestionLibraryItem.subject == subj)
        if origin_v:
            stmt = stmt.where(QuestionLibraryItem.origin == origin_v)
        if hidden in {"0", "1"}:
            stmt = stmt.where(QuestionLibraryItem.hidden == (1 if hidden == "1" else 0))
        if min_score is not None:
            stmt = stmt.where(QuestionLibraryItem.ai_score >= int(min_score))
        if qv:
            like = f"%{qv}%"
            stmt = stmt.where(or_(QuestionCache.stem.like(like), QuestionLibraryItem.question_id.like(like)))

        sort_key = sort.strip().lower()
        order_key = order.strip().lower()
        col = QuestionLibraryItem.updated_at if sort_key != "ai_score" else QuestionLibraryItem.ai_score
        stmt = stmt.order_by(desc(col) if order_key != "asc" else col.asc())

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = int((await session.execute(total_stmt)).scalar() or 0)

        rows = (await session.execute(stmt.limit(lim).offset(off))).all()

    items: List[Dict[str, Any]] = []
    for r in rows:
        items.append(
            {
                "question_id": r[0],
                "subject": r[1] or "",
                "origin": r[2] or "",
                "hidden": bool(r[3]),
                "ai_score": r[4],
                "ai_verdict": r[5] or "",
                "ai_summary": r[6] or "",
                "updated_at": r[7].isoformat() if r[7] else "",
                "stem": (r[8] or ""),
            }
        )

    return {"total": total, "items": items, "limit": lim, "offset": off}


async def set_hidden(*, user_id: str, question_id: str, hidden: bool) -> bool:
    uid = _normalize_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        return False

    async with async_session_maker() as session:
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
        await session.commit()
        return True


async def get_question_library_item(*, user_id: str, question_id: str) -> Optional[dict]:
    uid = _normalize_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        return None

    async with async_session_maker() as session:
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
        "ai_score": row.ai_score,
        "ai_verdict": row.ai_verdict or "",
        "ai_dimensions_json": row.ai_dimensions_json or "",
        "ai_summary": row.ai_summary or "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


async def list_unscored_question_ids(*, user_id: str, subject: str = "", limit: int = 50) -> List[str]:
    uid = _normalize_user_id(user_id)
    subj = str(subject or "").strip()
    lim = max(1, min(_as_int(limit, 50), 500))

    async with async_session_maker() as session:
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
