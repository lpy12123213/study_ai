from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select

from backend.database.engine import async_session_maker
from backend.database.schema import QuestionCache, UsedQuestion


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


async def get_question_cache(*, question_ids: Iterable[str]) -> Dict[str, dict]:
    ids = [str(x or "").strip() for x in (question_ids or []) if str(x or "").strip()]
    if not ids:
        return {}

    async with async_session_maker() as session:
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


async def upsert_question_cache(items: List[dict]) -> int:
    entries = [x for x in (items or []) if isinstance(x, dict)]
    if not entries:
        return 0

    async with async_session_maker() as session:
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
        await session.commit()
        return n


async def mark_used_questions(*, question_ids: Iterable[str], subject: str = "") -> int:
    ids = [str(x or "").strip() for x in (question_ids or []) if str(x or "").strip()]
    if not ids:
        return 0

    async with async_session_maker() as session:
        n = 0
        for qid in ids:
            try:
                await session.merge(UsedQuestion(question_id=qid, subject=str(subject or "").strip()))
                n += 1
            except Exception:
                continue
        await session.commit()
        return n


async def list_used_question_ids(*, limit: int = 20000, subject: Optional[str] = None) -> List[str]:
    limit = max(100, min(int(limit or 20000), 200000))
    subj = (subject or "").strip()

    async with async_session_maker() as session:
        stmt = select(UsedQuestion.question_id).limit(limit)
        if subj:
            stmt = stmt.where(UsedQuestion.subject == subj)
        result = await session.execute(stmt)
        ids = result.scalars().all()
        return [str(x).strip() for x in ids if str(x or "").strip()]

