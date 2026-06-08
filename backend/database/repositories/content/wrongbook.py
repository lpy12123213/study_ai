from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.srs import apply_mastery_delta, clamp_mastery, schedule_review
from backend.database.engine import async_session_maker
from backend.database.repositories.question.question_cache import get_question_cache
from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import WrongQuestion


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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _coerce_now(now: Optional[datetime]) -> datetime:
    if now is None:
        return _utcnow()
    if now.tzinfo is None:
        return now
    return now.astimezone(timezone.utc).replace(tzinfo=None)


def _iso(dt: Optional[datetime]) -> str:
    return dt.isoformat() if dt else ""


def _normalize_group(value: str, *, fallback: str) -> str:
    text = " ".join(str(value or "").strip().split())
    return text or fallback


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
        "ease_factor": float(row.ease_factor if row.ease_factor is not None else 2.5),
        "interval_days": int(row.interval_days or 0),
        "repetitions": int(row.repetitions or 0),
        "next_review_at": _iso(row.next_review_at),
        "last_reviewed_at": _iso(row.last_reviewed_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
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
    now: Optional[datetime] = None,
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
                now=now,
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
            row.mastery = clamp_mastery(mastery)
        if note is not None:
            row.note = str(note or "").strip()
        if tags is not None:
            cleaned_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
            row.tags_json = _json_dumps(cleaned_tags, default="[]")
        if source_ref is not None:
            row.source_ref_json = _json_dumps(source_ref, default="{}")
        if row.ease_factor is None:
            row.ease_factor = 2.5
        if row.interval_days is None:
            row.interval_days = 0
        if row.repetitions is None:
            row.repetitions = 0
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return _row_to_dict(row)

    cleaned_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
    review_now = _coerce_now(now)
    row = WrongQuestion(
        user_id=uid,
        question_id=qid,
        subject=str(subject or "").strip(),
        knowledge_point=str(knowledge_point or "").strip(),
        mastery=clamp_mastery(mastery) if mastery is not None else 0,
        note=str(note or "").strip(),
        tags_json=_json_dumps(cleaned_tags, default="[]"),
        source_ref_json=_json_dumps(source_ref or {}, default="{}"),
        ease_factor=2.5,
        interval_days=0,
        repetitions=0,
        next_review_at=review_now,
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


def _due_filters(*, user_id: str, subject: Optional[str], now: datetime) -> list[Any]:
    where = [
        WrongQuestion.user_id == user_id,
        or_(WrongQuestion.next_review_at.is_(None), WrongQuestion.next_review_at <= now),
    ]
    if subject:
        where.append(WrongQuestion.subject == str(subject).strip())
    return where


async def list_due_reviews(
    *,
    user_id: str,
    subject: Optional[str] = None,
    limit: int = 50,
    now: Optional[datetime] = None,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    review_now = _coerce_now(now)
    max_items = max(1, min(int(limit or 50), 200))
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_due_reviews(
                user_id=uid,
                subject=subject,
                limit=max_items,
                now=review_now,
                session=session,
            )

    stmt = (
        select(WrongQuestion)
        .where(and_(*_due_filters(user_id=uid, subject=subject, now=review_now)))
        .order_by(WrongQuestion.next_review_at.asc(), WrongQuestion.updated_at.asc())
        .limit(max_items)
    )
    res = await session.execute(stmt)
    rows = list(res.scalars().all())
    items = [_row_to_dict(row) for row in rows]
    cache = await get_question_cache(question_ids=[item["question_id"] for item in items], session=session)
    for item in items:
        item["question"] = cache.get(str(item.get("question_id") or ""), {})
    return items


async def count_due_reviews(
    *,
    user_id: str,
    subject: Optional[str] = None,
    now: Optional[datetime] = None,
    session: Optional[AsyncSession] = None,
) -> int:
    uid = _require_user_id(user_id)
    review_now = _coerce_now(now)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await count_due_reviews(user_id=uid, subject=subject, now=review_now, session=session)

    stmt = select(func.count(WrongQuestion.id)).where(and_(*_due_filters(user_id=uid, subject=subject, now=review_now)))
    return int((await session.execute(stmt)).scalar_one() or 0)


async def record_review(
    *,
    user_id: str,
    question_id: str,
    rating: str,
    now: Optional[datetime] = None,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        raise ValueError("missing_question_id")
    review_now = _coerce_now(now)

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await record_review(
                user_id=uid,
                question_id=qid,
                rating=rating,
                now=review_now,
                session=session,
            )
            await session.commit()
            return out

    res = await session.execute(select(WrongQuestion).where(WrongQuestion.user_id == uid, WrongQuestion.question_id == qid))
    row = res.scalar_one_or_none()
    if row is None:
        return None

    schedule = schedule_review(
        rating=rating,
        ease_factor=float(row.ease_factor if row.ease_factor is not None else 2.5),
        interval_days=int(row.interval_days or 0),
        repetitions=int(row.repetitions or 0),
        now=review_now,
    )
    row.mastery = apply_mastery_delta(row.mastery, rating)
    row.ease_factor = schedule["ease_factor"]
    row.interval_days = schedule["interval_days"]
    row.repetitions = schedule["repetitions"]
    row.next_review_at = schedule["next_review_at"]
    row.last_reviewed_at = review_now
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)


async def aggregate_mastery_by_knowledge_point(
    *,
    user_id: str,
    subject: Optional[str] = None,
    now: Optional[datetime] = None,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    review_now = _coerce_now(now)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await aggregate_mastery_by_knowledge_point(
                user_id=uid,
                subject=subject,
                now=review_now,
                session=session,
            )

    where = [WrongQuestion.user_id == uid]
    if subject:
        where.append(WrongQuestion.subject == str(subject).strip())
    res = await session.execute(select(WrongQuestion).where(and_(*where)))
    rows = list(res.scalars().all())

    subject_groups: dict[str, dict] = {}
    kp_groups: dict[tuple[str, str], dict] = {}
    for row in rows:
        row_subject = _normalize_group(row.subject, fallback="未标注")
        kp = _normalize_group(row.knowledge_point, fallback="未标注")
        mastery = clamp_mastery(row.mastery)
        is_due = row.next_review_at is None or row.next_review_at <= review_now

        subject_bucket = subject_groups.setdefault(
            row_subject,
            {"subject": row_subject, "count": 0, "mastery_sum": 0, "min_mastery": mastery, "due_count": 0},
        )
        subject_bucket["count"] += 1
        subject_bucket["mastery_sum"] += mastery
        subject_bucket["min_mastery"] = min(subject_bucket["min_mastery"], mastery)
        subject_bucket["due_count"] += 1 if is_due else 0

        kp_bucket = kp_groups.setdefault(
            (row_subject, kp),
            {
                "subject": row_subject,
                "knowledge_point": kp,
                "count": 0,
                "mastery_sum": 0,
                "min_mastery": mastery,
                "due_count": 0,
            },
        )
        kp_bucket["count"] += 1
        kp_bucket["mastery_sum"] += mastery
        kp_bucket["min_mastery"] = min(kp_bucket["min_mastery"], mastery)
        kp_bucket["due_count"] += 1 if is_due else 0

    def finalize(bucket: dict) -> dict:
        count = int(bucket["count"] or 0)
        avg = round(float(bucket["mastery_sum"] or 0) / count, 1) if count else 0.0
        return {
            key: value
            for key, value in {
                **bucket,
                "avg_mastery": avg,
            }.items()
            if key != "mastery_sum"
        }

    subjects = [finalize(bucket) for bucket in subject_groups.values()]
    knowledge_points = [finalize(bucket) for bucket in kp_groups.values()]
    subjects.sort(key=lambda item: (float(item["avg_mastery"]), str(item["subject"])))
    knowledge_points.sort(key=lambda item: (float(item["avg_mastery"]), str(item["knowledge_point"])))
    return {"subjects": subjects, "knowledge_points": knowledge_points}
