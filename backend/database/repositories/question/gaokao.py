from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.repositories.question.question_cache import upsert_question_cache
from backend.database.repositories.question.question_library import upsert_question_library_items
from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import GaokaoQuestionSource


def _required_text(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"missing_{field}")
    return normalized


def _source_values(*, user_id: str, question_id: str, source: Dict[str, Any]) -> Dict[str, Any]:
    try:
        exam_year = int(source.get("exam_year"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_exam_year") from exc
    if exam_year < 1952 or exam_year > 2100:
        raise ValueError("invalid_exam_year")

    return {
        "user_id": user_id,
        "question_id": question_id,
        "exam_year": exam_year,
        "region": _required_text(source.get("region"), field="region"),
        "paper_name": _required_text(source.get("paper_name"), field="paper_name"),
        "paper_variant": str(source.get("paper_variant") or "").strip(),
        "question_number": str(source.get("question_number") or "").strip(),
        "source_url": str(source.get("source_url") or "").strip(),
        "source_note": str(source.get("source_note") or "").strip(),
        "verified": 1 if bool(source.get("verified")) else 0,
    }


async def upsert_gaokao_questions(
    *,
    user_id: str,
    items: List[dict],
    session: Optional[AsyncSession] = None,
) -> dict:
    """原子写入题干缓存、用户题库成员关系和高考出处记录。"""

    uid = normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    entries = [dict(item) for item in (items or []) if isinstance(item, dict)]
    if not entries:
        return {"upserted": 0, "question_ids": []}

    own = session is None
    if own:
        async with async_session_maker() as session:
            result = await upsert_gaokao_questions(user_id=uid, items=entries, session=session)
            await session.commit()
            return result

    question_ids: list[str] = []
    seen_ids: set[str] = set()
    for item in entries:
        qid = _required_text(item.get("question_id"), field="question_id")
        if qid in seen_ids:
            raise ValueError("duplicate_question_id")
        seen_ids.add(qid)
        stem = _required_text(item.get("stem"), field="stem")
        subject = _required_text(item.get("subject"), field="subject")
        raw_source = item.get("source")
        if not isinstance(raw_source, dict):
            raise ValueError("missing_source")
        source_values = _source_values(user_id=uid, question_id=qid, source=raw_source)

        await upsert_question_cache(
            [
                {
                    "question_id": qid,
                    "subject": subject,
                    "stem": stem,
                    "answer": item.get("answer"),
                    "analysis": item.get("analysis"),
                    "question_type": item.get("question_type"),
                    "difficulty": item.get("difficulty"),
                    "difficulty_value": item.get("difficulty_value"),
                    "knowledge_point": item.get("knowledge_point"),
                    "knowledge_points": item.get("knowledge_points"),
                    "source": source_values["paper_name"],
                    "source_url": source_values["source_url"],
                    "date": str(source_values["exam_year"]),
                }
            ],
            session=session,
        )
        await upsert_question_library_items(
            user_id=uid,
            items=[
                {
                    "question_id": qid,
                    "subject": subject,
                    "origin": str(item.get("origin") or "media").strip(),
                }
            ],
            session=session,
        )

        stmt = sqlite_insert(GaokaoQuestionSource).values(**source_values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "question_id"],
            set_={key: value for key, value in source_values.items() if key not in {"user_id", "question_id"}},
        )
        await session.execute(stmt)
        question_ids.append(qid)

    await session.flush()
    return {"upserted": len(question_ids), "question_ids": question_ids}
