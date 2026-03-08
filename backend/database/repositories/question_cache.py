from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.schema import QuestionCache, UsedQuestion, UsedQuestionUser


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on"}


def _used_questions_user_scope_enabled() -> bool:
    scope = str(os.getenv("USED_QUESTIONS_SCOPE") or "").strip().lower()
    if scope in {"user", "per_user", "user_id"}:
        return True
    if scope in {"global", ""}:
        return False
    # Back-compat: allow `USED_QUESTIONS_PER_USER=1`.
    return _env_truthy("USED_QUESTIONS_PER_USER", default=False)


def _clip(text: str, max_chars: int) -> str:
    t = str(text or "")
    if max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def _to_json_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return ""
    return ""


async def get_question_cache(
    *,
    question_ids: Iterable[str],
    session: Optional[AsyncSession] = None,
) -> Dict[str, dict]:
    ids = [str(x or "").strip() for x in (question_ids or []) if str(x or "").strip()]
    if not ids:
        return {}

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_question_cache(question_ids=ids, session=session)

    result = await session.execute(select(QuestionCache).where(QuestionCache.question_id.in_(ids)))
    rows = list(result.scalars().all())

    out: Dict[str, dict] = {}
    for r in rows:
        out[str(r.question_id)] = {
            "question_id": r.question_id,
            "subject": r.subject,
            "question_type": r.question_type,
            "difficulty": r.difficulty,
            "knowledge_point": r.knowledge_point,
            "source_url": r.source_url,
            "stem": r.stem or "",
            "stem_fingerprint": r.stem_fingerprint or "",
            "answer": r.answer or "",
            "analysis": r.analysis or "",
            "difficulty_value": r.difficulty_value,
            "quality_score": int(r.quality_score or 0),
            "quality_flags": r.quality_flags or "",
            "knowledge_points_json": r.knowledge_points_json or "",
            "source": r.source or "",
            "date": r.date or "",
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        }
    return out


async def upsert_question_cache(items: List[dict], *, session: Optional[AsyncSession] = None) -> int:
    entries = [x for x in (items or []) if isinstance(x, dict)]
    if not entries:
        return 0

    own = session is None
    if own:
        async with async_session_maker() as session:
            n = await upsert_question_cache(entries, session=session)
            await session.commit()
            return n

    n = 0
    for it in entries:
        qid = str(it.get("question_id") or "").strip()
        if not qid:
            continue
        row = QuestionCache(
            question_id=qid,
            subject=str(it.get("subject") or "").strip(),
            question_type=str(it.get("question_type") or it.get("type") or "").strip(),
            difficulty=str(it.get("difficulty") or "").strip(),
            knowledge_point=str(it.get("knowledge_point") or "").strip(),
            source_url=str(it.get("source_url") or "").strip(),
            stem=_clip(str(it.get("stem") or ""), 20000),
            stem_fingerprint=str(it.get("stem_fingerprint") or it.get("stem_fp") or "").strip(),
            answer=_clip(str(it.get("answer") or it.get("solution") or ""), 12000),
            analysis=_clip(str(it.get("analysis") or it.get("explanation") or ""), 20000),
            difficulty_value=it.get("difficulty_value"),
            quality_score=int(it.get("quality_score") or 0),
            quality_flags=_to_json_str(it.get("quality_flags") or ""),
            knowledge_points_json=_to_json_str(it.get("knowledge_points_json") or it.get("knowledge_points") or ""),
            source=str(it.get("source") or "").strip(),
            date=str(it.get("date") or "").strip(),
        )
        try:
            await session.merge(row)
            n += 1
        except Exception:
            continue
    await session.flush()
    return n


async def mark_used_questions(
    *,
    question_ids: Iterable[str],
    subject: str = "",
    user_id: Optional[str] = None,
    session: Optional[AsyncSession] = None,
) -> int:
    ids = [str(x or "").strip() for x in (question_ids or []) if str(x or "").strip()]
    if not ids:
        return 0

    user_scope = _used_questions_user_scope_enabled()
    uid = str(user_id or "").strip()
    if user_scope and not uid:
        return 0

    own = session is None
    if own:
        async with async_session_maker() as session:
            n = await mark_used_questions(question_ids=ids, subject=subject, user_id=user_id, session=session)
            await session.commit()
            return n

    n = 0
    for qid in ids:
        try:
            if user_scope:
                await session.merge(UsedQuestionUser(user_id=uid, question_id=qid, subject=str(subject or "").strip()))
            else:
                await session.merge(UsedQuestion(question_id=qid, subject=str(subject or "").strip()))
            n += 1
        except Exception:
            continue
    await session.flush()
    return n


async def list_used_question_ids(
    *,
    limit: int = 20000,
    subject: Optional[str] = None,
    user_id: Optional[str] = None,
    session: Optional[AsyncSession] = None,
) -> List[str]:
    limit = max(100, min(int(limit or 20000), 200000))
    subj = (subject or "").strip()
    user_scope = _used_questions_user_scope_enabled()
    uid = str(user_id or "").strip()
    if user_scope and not uid:
        return []

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_used_question_ids(limit=limit, subject=subject, user_id=user_id, session=session)

    stmt = select(UsedQuestionUser.question_id if user_scope else UsedQuestion.question_id).limit(limit)
    if subj:
        if user_scope:
            stmt = stmt.where(UsedQuestionUser.subject == subj)
        else:
            stmt = stmt.where(UsedQuestion.subject == subj)
    if user_scope:
        stmt = stmt.where(UsedQuestionUser.user_id == uid)
    result = await session.execute(stmt)
    ids = result.scalars().all()
    return [str(x).strip() for x in ids if str(x or "").strip()]
