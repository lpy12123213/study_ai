"""Async CRUD for essay evaluation history rows."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.time_utils import utcnow
from backend.database.engine import async_session_maker
from backend.database.schema import EssayEvaluation


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64]


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _safe_loads(raw: str, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _row_to_dict(row: EssayEvaluation, *, include_text: bool = True) -> Dict[str, Any]:
    feedback = _safe_loads(row.feedback_json or "{}", {}) or {}
    out: Dict[str, Any] = {
        "id": int(row.id),
        "user_id": str(row.user_id or ""),
        "subject": str(row.subject or ""),
        "topic": str(row.topic or ""),
        "essay_type": str(row.essay_type or ""),
        "grade_band": str(row.grade_band or ""),
        "language": str(row.language or "zh"),
        "score_total": float(row.score_total or 0.0),
        "score_max": float(row.score_max or 0.0),
        "grade": str(row.grade or ""),
        "scores": _safe_loads(row.scores_json or "[]", []) or [],
        "summary": str(feedback.get("summary") or ""),
        "strengths": list(feedback.get("strengths") or []),
        "weaknesses": list(feedback.get("weaknesses") or []),
        "suggestions": list(feedback.get("suggestions") or []),
        "paragraph_feedback": list(feedback.get("paragraph_feedback") or []),
        "rewrite": str(feedback.get("rewrite") or ""),
        "model": str(row.model or ""),
        "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else None,
        "updated_at": row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else None,
    }
    if include_text:
        out["essay_text"] = str(row.essay_text or "")
        out["requirements"] = str(row.requirements or "")
    return out


async def insert_evaluation(
    *,
    user_id: str,
    essay_text: str,
    subject: str,
    topic: str,
    essay_type: str,
    grade_band: str,
    language: str,
    requirements: str,
    score_total: float,
    score_max: float,
    grade: str,
    scores: List[Dict[str, Any]],
    feedback: Dict[str, Any],
    model: str,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    uid = _require_user_id(user_id)

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await insert_evaluation(
                user_id=uid,
                essay_text=essay_text,
                subject=subject,
                topic=topic,
                essay_type=essay_type,
                grade_band=grade_band,
                language=language,
                requirements=requirements,
                score_total=score_total,
                score_max=score_max,
                grade=grade,
                scores=scores,
                feedback=feedback,
                model=model,
                session=session,
            )
            await session.commit()
            return out

    now = utcnow().replace(tzinfo=None)
    row = EssayEvaluation(
        user_id=uid,
        subject=str(subject or "")[:40],
        topic=str(topic or "")[:200],
        essay_type=str(essay_type or "")[:32],
        grade_band=str(grade_band or "")[:32],
        language=str(language or "zh")[:8],
        essay_text=str(essay_text or ""),
        requirements=str(requirements or "")[:1000],
        score_total=float(score_total or 0.0),
        score_max=float(score_max or 0.0),
        grade=str(grade or "")[:32],
        scores_json=json.dumps(list(scores or []), ensure_ascii=False),
        feedback_json=json.dumps(dict(feedback or {}), ensure_ascii=False),
        model=str(model or "")[:100],
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)


async def get_evaluation(
    *, user_id: str, evaluation_id: int, session: Optional[AsyncSession] = None
) -> Optional[Dict[str, Any]]:
    uid = _normalize_user_id(user_id)
    if not uid:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_evaluation(user_id=uid, evaluation_id=evaluation_id, session=session)

    res = await session.execute(
        select(EssayEvaluation).where(
            EssayEvaluation.id == int(evaluation_id), EssayEvaluation.user_id == uid
        )
    )
    row = res.scalar_one_or_none()
    return _row_to_dict(row) if row else None


async def list_evaluations(
    *,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    session: Optional[AsyncSession] = None,
) -> List[Dict[str, Any]]:
    uid = _normalize_user_id(user_id)
    if not uid:
        return []

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_evaluations(user_id=uid, limit=limit, offset=offset, session=session)

    safe_limit = max(1, min(int(limit or 50), 200))
    safe_offset = max(0, min(int(offset or 0), 100_000))
    stmt = (
        select(EssayEvaluation)
        .where(EssayEvaluation.user_id == uid)
        .order_by(EssayEvaluation.created_at.desc())
        .limit(safe_limit)
        .offset(safe_offset)
    )
    res = await session.execute(stmt)
    # ``include_text=False`` keeps history listings light: full essay text is
    # only fetched on demand via ``get_evaluation``.
    return [_row_to_dict(row, include_text=False) for row in res.scalars().all()]


async def delete_evaluation(
    *, user_id: str, evaluation_id: int, session: Optional[AsyncSession] = None
) -> bool:
    uid = _normalize_user_id(user_id)
    if not uid:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await delete_evaluation(user_id=uid, evaluation_id=evaluation_id, session=session)
            await session.commit()
            return ok

    res = await session.execute(
        select(EssayEvaluation).where(
            EssayEvaluation.id == int(evaluation_id), EssayEvaluation.user_id == uid
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    return True
