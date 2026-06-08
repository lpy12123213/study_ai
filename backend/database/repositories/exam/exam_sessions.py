from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.time_utils import utcnow_naive
from backend.database.engine import async_session_maker
from backend.database.repositories.question.papers import get_paper
from backend.database.repositories.question.question_cache import get_question_cache
from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import ExamResult, ExamSession, StudentAnswer


def _normalize_user_id(user_id: str) -> str:
    return normalize_user_id(user_id)


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _to_json_str(value: Any, default: str = "[]") -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return default
    return default


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x or "").strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            obj = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return [raw]
        if isinstance(obj, list):
            return [str(x).strip() for x in obj if str(x or "").strip()]
    return []


def _json_obj(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            obj = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(obj) if isinstance(obj, dict) else {}
    return {}


def _dt(value: Any) -> str | None:
    return value.isoformat() if value else None


def _question_max_score(question: dict) -> float:
    raw = question.get("score") or question.get("max_score") or question.get("points")
    try:
        score = float(raw)
    except (TypeError, ValueError):
        score = 0.0
    if score > 0:
        return score
    qtype = str(question.get("type") or question.get("question_type") or "").lower()
    if any(key in qtype for key in ("short", "calculation", "essay", "解答", "简答", "计算", "论述", "作文")):
        return 10.0
    return 5.0


def _question_to_exam(question: dict) -> dict:
    qtype = str(question.get("type") or question.get("question_type") or "").strip()
    return {
        "question_id": str(question.get("question_id") or "").strip(),
        "order": int(question.get("order") or question.get("question_order") or 0),
        "type": qtype,
        "question_type": qtype,
        "stem": str(question.get("stem") or "").strip(),
        "difficulty": str(question.get("difficulty") or "").strip(),
        "knowledge_point": str(question.get("knowledge_point") or "").strip(),
        "source_url": str(question.get("source_url") or "").strip(),
        "max_score": _question_max_score(question),
    }


def _answer_to_dict(answer: StudentAnswer) -> dict:
    return {
        "id": int(answer.id or 0),
        "session_id": str(answer.session_id or ""),
        "question_id": str(answer.question_id or ""),
        "question_type": str(answer.question_type or ""),
        "question_order": int(answer.question_order or 0),
        "selected_options": _json_list(answer.selected_options_json),
        "fill_blank_text": str(answer.fill_blank_text or ""),
        "handwriting_image_path": str(answer.handwriting_image_path or ""),
        "text_answer": str(answer.text_answer or ""),
        "is_correct": None if answer.is_correct is None else bool(answer.is_correct),
        "score": float(answer.score or 0.0),
        "max_score": float(answer.max_score or 0.0),
        "grading_json": _json_obj(answer.grading_json),
        "auto_saved_at": _dt(answer.auto_saved_at),
    }


def _result_to_dict(result: ExamResult) -> dict:
    return {
        "id": int(result.id or 0),
        "session_id": str(result.session_id or ""),
        "total_score": float(result.total_score or 0.0),
        "max_score": float(result.max_score or 0.0),
        "score_ratio": float(result.score_ratio or 0.0),
        "objective_correct": int(result.objective_correct or 0),
        "objective_total": int(result.objective_total or 0),
        "subjective_score": float(result.subjective_score or 0.0),
        "subjective_max": float(result.subjective_max or 0.0),
        "breakdown": _json_list_or_obj(result.breakdown_json, default=[]),
        "ai_feedback": _json_obj(result.ai_feedback_json),
        "created_at": _dt(result.created_at),
    }


def _json_list_or_obj(value: Any, *, default: list) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            obj = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return default
        return obj if isinstance(obj, list) else default
    return default


async def create_exam_session(
    *,
    user_id: str,
    paper_id: int,
    mode: str = "untimed",
    time_limit_minutes: Optional[int] = None,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await create_exam_session(
                user_id=uid,
                paper_id=paper_id,
                mode=mode,
                time_limit_minutes=time_limit_minutes,
                session=session,
            )
            await session.commit()
            return out

    paper = await get_paper(user_id=uid, paper_id=int(paper_id), session=session)
    if not paper:
        raise ValueError("paper_not_found")

    normalized_mode = "timed" if str(mode or "").strip().lower() == "timed" else "untimed"
    minutes = None
    if normalized_mode == "timed":
        try:
            minutes = int(time_limit_minutes or 0)
        except (TypeError, ValueError):
            minutes = 0
        minutes = max(1, min(minutes, 24 * 60))

    now = utcnow_naive()
    expires_at = now + timedelta(minutes=minutes) if minutes else None
    row = ExamSession(
        id=uuid.uuid4().hex,
        user_id=uid,
        paper_id=int(paper_id),
        paper_name=str(paper.get("paper_name") or "").strip() or "未命名试卷",
        mode=normalized_mode,
        time_limit_minutes=minutes,
        started_at=now,
        expires_at=expires_at,
        status="in_progress",
        max_score=sum(_question_max_score(q) for q in paper.get("questions") or [] if isinstance(q, dict)),
    )
    session.add(row)
    await session.flush()
    return await get_exam_session(user_id=uid, session_id=row.id, session=session) or {"session_id": row.id}


async def _load_session_row(
    *,
    user_id: str,
    session_id: str,
    session: AsyncSession,
) -> ExamSession | None:
    result = await session.execute(
        select(ExamSession)
        .options(selectinload(ExamSession.answers), selectinload(ExamSession.result))
        .where(ExamSession.id == str(session_id or "").strip(), ExamSession.user_id == _require_user_id(user_id))
    )
    return result.scalar_one_or_none()


async def _expire_if_needed(row: ExamSession, *, session: AsyncSession) -> None:
    if row.status != "in_progress" or not row.expires_at:
        return
    if row.expires_at > utcnow_naive():
        return
    row.status = "expired"
    row.updated_at = utcnow_naive()
    await session.flush()


async def get_exam_session(
    *,
    user_id: str,
    session_id: str,
    include_answers: bool = False,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_exam_session(
                user_id=uid,
                session_id=session_id,
                include_answers=include_answers,
                session=session,
            )

    row = await _load_session_row(user_id=uid, session_id=session_id, session=session)
    if not row:
        return None
    await _expire_if_needed(row, session=session)
    paper = await get_paper(user_id=uid, paper_id=int(row.paper_id), session=session)
    raw_questions = [q for q in (paper or {}).get("questions") or [] if isinstance(q, dict)]
    qids = [str(q.get("question_id") or "").strip() for q in raw_questions if str(q.get("question_id") or "").strip()]
    cache = await get_question_cache(question_ids=qids, session=session) if qids else {}
    paper_questions: list[dict] = []
    for q in raw_questions:
        qid = str(q.get("question_id") or "").strip()
        cached = cache.get(qid) if qid else None
        if not isinstance(cached, dict):
            paper_questions.append(q)
            continue
        merged = dict(q)
        for key in ("stem", "answer", "analysis", "source_url"):
            if not str(merged.get(key) or "").strip() and str(cached.get(key) or "").strip():
                merged[key] = str(cached.get(key) or "").strip()
        paper_questions.append(merged)
    question_details = {str(q.get("question_id") or "").strip(): q for q in paper_questions}
    questions = [_question_to_exam(q) for q in paper_questions]
    answers = {_answer_to_dict(a)["question_id"]: _answer_to_dict(a) for a in row.answers}

    out_questions: list[dict] = []
    for q in questions:
        item = dict(q)
        if include_answers:
            detail = question_details.get(str(q.get("question_id") or "").strip(), {})
            item["answer"] = str(detail.get("answer") or "")
            item["analysis"] = str(detail.get("analysis") or "")
        if q["question_id"] in answers:
            item["student_answer"] = answers[q["question_id"]]
        out_questions.append(item)

    return {
        "session_id": row.id,
        "paper_id": int(row.paper_id),
        "paper_name": row.paper_name,
        "mode": row.mode,
        "time_limit_minutes": row.time_limit_minutes,
        "started_at": _dt(row.started_at),
        "submitted_at": _dt(row.submitted_at),
        "expires_at": _dt(row.expires_at),
        "status": row.status,
        "total_score": float(row.total_score or 0.0),
        "max_score": float(row.max_score or 0.0),
        "questions": out_questions,
        "answers": list(answers.values()) if include_answers else [],
        "result": _result_to_dict(row.result) if row.result else None,
    }


async def list_user_sessions(
    *,
    user_id: str,
    paper_id: Optional[int] = None,
    limit: int = 50,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_user_sessions(user_id=uid, paper_id=paper_id, limit=limit, session=session)

    stmt = select(ExamSession).where(ExamSession.user_id == uid)
    if paper_id:
        stmt = stmt.where(ExamSession.paper_id == int(paper_id))
    stmt = stmt.order_by(ExamSession.created_at.desc()).limit(max(1, min(int(limit or 50), 200)))
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "session_id": row.id,
            "paper_id": int(row.paper_id),
            "paper_name": row.paper_name,
            "mode": row.mode,
            "status": row.status,
            "total_score": float(row.total_score or 0.0),
            "max_score": float(row.max_score or 0.0),
            "started_at": _dt(row.started_at),
            "submitted_at": _dt(row.submitted_at),
            "expires_at": _dt(row.expires_at),
            "created_at": _dt(row.created_at),
        }
        for row in rows
    ]


async def save_answer(
    *,
    user_id: str,
    session_id: str,
    question_id: str,
    answer_data: Dict[str, Any],
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await save_answer(
                user_id=uid,
                session_id=session_id,
                question_id=question_id,
                answer_data=answer_data,
                session=session,
            )
            await session.commit()
            return out

    row = await _load_session_row(user_id=uid, session_id=session_id, session=session)
    if not row:
        raise ValueError("session_not_found")
    await _expire_if_needed(row, session=session)
    if row.status != "in_progress":
        raise ValueError("session_not_editable")

    paper = await get_paper(user_id=uid, paper_id=int(row.paper_id), session=session)
    questions = [_question_to_exam(q) for q in (paper or {}).get("questions") or [] if isinstance(q, dict)]
    question = next((q for q in questions if q["question_id"] == str(question_id or "").strip()), None)
    if not question:
        raise ValueError("question_not_found")

    selected = answer_data.get("selected_options")
    if selected is None:
        selected = answer_data.get("selectedOptions")
    now = utcnow_naive()
    payload = {
        "session_id": row.id,
        "user_id": uid,
        "question_id": question["question_id"],
        "question_type": str(answer_data.get("question_type") or answer_data.get("questionType") or question["type"]),
        "question_order": int(question.get("order") or 0),
        "selected_options_json": _to_json_str(selected or []),
        "fill_blank_text": str(answer_data.get("fill_blank_text") or answer_data.get("fillBlankText") or ""),
        "handwriting_image_path": str(answer_data.get("handwriting_image_path") or answer_data.get("handwritingImagePath") or ""),
        "text_answer": str(answer_data.get("text_answer") or answer_data.get("textAnswer") or ""),
        "max_score": float(question.get("max_score") or 0.0),
        "auto_saved_at": now,
        "updated_at": now,
    }
    stmt = sqlite_insert(StudentAnswer).values(created_at=now, **payload)
    update_cols = {k: v for k, v in payload.items() if k not in {"session_id", "user_id", "question_id"}}
    stmt = stmt.on_conflict_do_update(
        index_elements=["session_id", "question_id"],
        set_=update_cols,
    )
    await session.execute(stmt)
    await session.flush()
    result = await session.execute(
        select(StudentAnswer).where(StudentAnswer.session_id == row.id, StudentAnswer.question_id == question["question_id"])
    )
    answer = result.scalar_one()
    return _answer_to_dict(answer)


async def batch_save_answers(
    *,
    user_id: str,
    session_id: str,
    answers: List[Dict[str, Any]],
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await batch_save_answers(user_id=uid, session_id=session_id, answers=answers, session=session)
            await session.commit()
            return out
    out = []
    for item in answers or []:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or item.get("questionId") or "").strip()
        if not qid:
            continue
        out.append(await save_answer(user_id=uid, session_id=session_id, question_id=qid, answer_data=item, session=session))
    return out


async def get_session_answers(
    *,
    user_id: str,
    session_id: str,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_session_answers(user_id=uid, session_id=session_id, session=session)

    row = await _load_session_row(user_id=uid, session_id=session_id, session=session)
    if not row:
        raise ValueError("session_not_found")
    return [_answer_to_dict(a) for a in sorted(row.answers, key=lambda a: int(a.question_order or 0))]


async def update_answer_score(
    *,
    user_id: str,
    answer_id: int,
    score_data: Dict[str, Any],
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await update_answer_score(user_id=uid, answer_id=answer_id, score_data=score_data, session=session)
            await session.commit()
            return out

    result = await session.execute(
        select(StudentAnswer)
        .options(selectinload(StudentAnswer.session))
        .where(StudentAnswer.id == int(answer_id), StudentAnswer.user_id == uid)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise ValueError("answer_not_found")
    parent = row.session
    if not parent or str(parent.status or "").strip() != "in_progress":
        raise ValueError("session_not_in_progress")
    if "is_correct" in score_data:
        value = score_data.get("is_correct")
        row.is_correct = None if value is None else int(bool(value))
    row.score = float(score_data.get("score") or 0.0)
    row.max_score = float(score_data.get("max_score") or score_data.get("maxScore") or row.max_score or 0.0)
    row.grading_json = _to_json_str(score_data.get("grading_json") or score_data.get("gradingJson") or {}, default="{}")
    row.updated_at = utcnow_naive()
    await session.flush()
    return _answer_to_dict(row)


async def submit_session(
    *,
    user_id: str,
    session_id: str,
    total_score: float,
    max_score: float,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await submit_session(
                user_id=uid,
                session_id=session_id,
                total_score=total_score,
                max_score=max_score,
                session=session,
            )
            await session.commit()
            return out

    row = await _load_session_row(user_id=uid, session_id=session_id, session=session)
    if not row:
        raise ValueError("session_not_found")
    if str(row.status or "").strip() != "in_progress":
        raise ValueError("session_not_in_progress")
    row.status = "submitted"
    row.submitted_at = utcnow_naive()
    row.total_score = float(total_score or 0.0)
    row.max_score = float(max_score or 0.0)
    row.updated_at = utcnow_naive()
    await session.flush()
    return await get_exam_session(user_id=uid, session_id=session_id, include_answers=True, session=session) or {}


async def create_exam_result(
    *,
    user_id: str,
    session_id: str,
    result_data: Dict[str, Any],
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await create_exam_result(user_id=uid, session_id=session_id, result_data=result_data, session=session)
            await session.commit()
            return out

    row = await _load_session_row(user_id=uid, session_id=session_id, session=session)
    if not row:
        raise ValueError("session_not_found")
    now = utcnow_naive()
    payload = {
        "session_id": row.id,
        "user_id": uid,
        "total_score": float(result_data.get("total_score") or result_data.get("totalScore") or 0.0),
        "max_score": float(result_data.get("max_score") or result_data.get("maxScore") or 0.0),
        "score_ratio": float(result_data.get("score_ratio") or result_data.get("scoreRatio") or 0.0),
        "objective_correct": int(result_data.get("objective_correct") or result_data.get("objectiveCorrect") or 0),
        "objective_total": int(result_data.get("objective_total") or result_data.get("objectiveTotal") or 0),
        "subjective_score": float(result_data.get("subjective_score") or result_data.get("subjectiveScore") or 0.0),
        "subjective_max": float(result_data.get("subjective_max") or result_data.get("subjectiveMax") or 0.0),
        "breakdown_json": _to_json_str(result_data.get("breakdown") or [], default="[]"),
        "ai_feedback_json": _to_json_str(result_data.get("ai_feedback") or result_data.get("aiFeedback") or {}, default="{}"),
        "updated_at": now,
    }
    stmt = sqlite_insert(ExamResult).values(created_at=now, **payload)
    update_cols = {k: v for k, v in payload.items() if k not in {"session_id", "user_id"}}
    stmt = stmt.on_conflict_do_update(index_elements=["session_id"], set_=update_cols)
    await session.execute(stmt)
    await session.flush()
    result = await session.execute(select(ExamResult).where(ExamResult.session_id == row.id, ExamResult.user_id == uid))
    saved = result.scalar_one()
    return _result_to_dict(saved)


async def get_exam_result(
    *,
    user_id: str,
    session_id: str,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_exam_result(user_id=uid, session_id=session_id, session=session)
    result = await session.execute(select(ExamResult).where(ExamResult.session_id == str(session_id or "").strip(), ExamResult.user_id == uid))
    row = result.scalar_one_or_none()
    return _result_to_dict(row) if row else None
