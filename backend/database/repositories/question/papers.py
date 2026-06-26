from __future__ import annotations

import json
from typing import Any, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.logging_utils import get_logger
from backend.core.settings import env_bool
from backend.database.engine import async_session_maker
from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import Paper, PaperQuestion, QuestionCache

logger = get_logger(__name__)


def _to_json_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) or isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return ""
    return ""


def _normalize_user_id(user_id: str) -> str:
    return normalize_user_id(user_id)


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid



def _paper_storage_flags() -> tuple[bool, bool, bool]:
    store_all = env_bool("PAPER_STORE_CONTENT", default=False)
    store_stem = env_bool("PAPER_STORE_STEM", default=store_all)
    store_answer = env_bool("PAPER_STORE_ANSWER", default=store_all)
    store_analysis = env_bool("PAPER_STORE_ANALYSIS", default=store_all)
    return store_stem, store_answer, store_analysis


def _infer_paper_source_mode(question_ids: list[str]) -> str:
    ids = [str(x or "").strip() for x in (question_ids or []) if str(x or "").strip()]
    has_digits = any(x.isdigit() for x in ids)
    has_non_digits = any(not x.isdigit() for x in ids)
    if has_digits and has_non_digits:
        return "hybrid"
    return "zujuan" if has_digits else "local"


def _cache_item_has_content(item: QuestionCache) -> bool:
    return any(
        str(value or "").strip()
        for value in (
            getattr(item, "stem", ""),
            getattr(item, "answer", ""),
            getattr(item, "analysis", ""),
        )
    )


async def save_paper(
    *,
    user_id: str,
    paper_name: str,
    questions: List[dict],
    session: Optional[AsyncSession] = None,
) -> int:
    """保存试卷并写入题目快照（以及本地题目缓存）。"""

    uid = _require_user_id(user_id)

    qids = []
    for q_data in questions or []:
        payload = {"question_id": q_data} if isinstance(q_data, str) else dict(q_data or {})
        qid = str(payload.get("question_id") or "").strip()
        if qid:
            qids.append(qid)
    source_mode = _infer_paper_source_mode(qids)

    own = session is None
    if own:
        async with async_session_maker() as session:
            paper_id = await save_paper(user_id=uid, paper_name=paper_name, questions=questions, session=session)
            await session.commit()
            return paper_id

    paper = Paper(user_id=uid, paper_name=str(paper_name or "").strip() or "未命名试卷")
    session.add(paper)
    await session.flush()
    await session.refresh(paper)

    cache_items: List[QuestionCache] = []
    store_stem, store_answer, store_analysis = _paper_storage_flags()
    force_cache_content = source_mode in {"hybrid", "local"}
    cache_store_stem = store_stem or force_cache_content
    cache_store_answer = store_answer or force_cache_content
    cache_store_analysis = store_analysis or force_cache_content

    for i, q_data in enumerate(questions or []):
        payload = {"question_id": q_data} if isinstance(q_data, str) else dict(q_data or {})

        qid = str(payload.get("question_id") or "").strip()
        q_type = str(payload.get("type") or payload.get("question_type") or "").strip()
        q_diff = str(payload.get("difficulty") or "").strip()
        q_knowledge = str(payload.get("knowledge_point") or "").strip()
        q_source_url = str(payload.get("source_url") or "").strip()

        stem = str(payload.get("stem") or "").strip() if store_stem else ""
        stem_fp = str(payload.get("stem_fingerprint") or payload.get("stem_fp") or "").strip() if store_stem else ""
        difficulty_value = payload.get("difficulty_value")
        quality_score = int(payload.get("quality_score") or 0)
        quality_flags = payload.get("quality_flags") or ""
        knowledge_points_json = payload.get("knowledge_points_json") or payload.get("knowledge_points") or ""
        source = str(payload.get("source") or "").strip()
        date = str(payload.get("date") or "").strip()

        answer = str(payload.get("answer") or payload.get("solution") or "").strip() if store_answer else ""
        analysis = str(payload.get("analysis") or payload.get("explanation") or "").strip() if store_analysis else ""
        cache_stem = str(payload.get("stem") or "").strip() if cache_store_stem else ""
        cache_stem_fp = (
            str(payload.get("stem_fingerprint") or payload.get("stem_fp") or "").strip() if cache_store_stem else ""
        )
        cache_answer = (
            str(payload.get("answer") or payload.get("solution") or "").strip() if cache_store_answer else ""
        )
        cache_analysis = (
            str(payload.get("analysis") or payload.get("explanation") or "").strip() if cache_store_analysis else ""
        )

        pq = PaperQuestion(
            user_id=uid,
            paper_id=paper.id,
            question_id=qid,
            question_order=i + 1,
            question_type=q_type,
            difficulty=q_diff,
            knowledge_point=q_knowledge,
            source_url=q_source_url,
            stem=stem,
            stem_fingerprint=stem_fp,
            difficulty_value=difficulty_value,
            quality_score=quality_score,
            quality_flags=_to_json_str(quality_flags),
            knowledge_points_json=_to_json_str(knowledge_points_json),
            source=source,
            date=date,
            answer=answer,
            analysis=analysis,
        )
        session.add(pq)

        if qid:
            cache_items.append(
                QuestionCache(
                    question_id=qid,
                    subject=str(payload.get("subject") or "").strip(),
                    question_type=q_type,
                    difficulty=q_diff,
                    knowledge_point=q_knowledge,
                    source_url=q_source_url,
                    stem=cache_stem,
                    stem_fingerprint=cache_stem_fp,
                    answer=cache_answer,
                    analysis=cache_analysis,
                    difficulty_value=difficulty_value,
                    quality_score=quality_score,
                    quality_flags=_to_json_str(quality_flags),
                    knowledge_points_json=_to_json_str(knowledge_points_json),
                    source=source,
                    date=date,
                )
            )

    for item in cache_items:
        if not _cache_item_has_content(item):
            continue
        try:
            await session.merge(item)
        except SQLAlchemyError:
            logger.exception("paper_question_cache_merge_failed")

    await session.flush()
    return int(paper.id)


async def add_questions_to_paper(
    *,
    user_id: str,
    paper_id: int,
    questions: List[dict],
    session: Optional[AsyncSession] = None,
) -> int:
    """向现有试卷追加题目（并写入题目缓存）。

    Returns:
        appended_count
    """

    pid = int(paper_id or 0)
    if pid <= 0:
        raise ValueError("invalid_paper_id")

    entries = [q for q in (questions or []) if isinstance(q, (dict, str))]
    if not entries:
        return 0

    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            appended_count = await add_questions_to_paper(
                user_id=uid,
                paper_id=pid,
                questions=questions,
                session=session,
            )
            await session.commit()
            return appended_count

    result = await session.execute(select(Paper).where(Paper.id == pid, Paper.user_id == uid))
    paper = result.scalar_one_or_none()
    if not paper:
        raise ValueError("paper_not_found")

    max_order_res = await session.execute(
        select(func.max(PaperQuestion.question_order)).where(
            PaperQuestion.user_id == uid,
            PaperQuestion.paper_id == pid,
        )
    )
    max_order = int(max_order_res.scalar() or 0)

    existing_ids_res = await session.execute(
        select(PaperQuestion.question_id).where(
            PaperQuestion.user_id == uid,
            PaperQuestion.paper_id == pid,
        )
    )
    existing_ids = {str(x).strip() for x in existing_ids_res.scalars().all() if str(x or "").strip()}
    existing_mode = _infer_paper_source_mode(list(existing_ids))

    incoming_ids = []
    for q_data in entries:
        payload = {"question_id": q_data} if isinstance(q_data, str) else dict(q_data or {})
        qid = str(payload.get("question_id") or "").strip()
        if qid and qid not in existing_ids:
            incoming_ids.append(qid)
    incoming_mode = _infer_paper_source_mode(incoming_ids)
    combined_mode = _infer_paper_source_mode(list(existing_ids) + incoming_ids)

    cache_items: List[QuestionCache] = []
    appended = 0
    store_stem, store_answer, store_analysis = _paper_storage_flags()
    force_cache_content = combined_mode in {"hybrid", "local"} or existing_mode == "local" or incoming_mode == "local"
    cache_store_stem = store_stem or force_cache_content
    cache_store_answer = store_answer or force_cache_content
    cache_store_analysis = store_analysis or force_cache_content

    for q_data in entries:
        payload = {"question_id": q_data} if isinstance(q_data, str) else dict(q_data or {})
        qid = str(payload.get("question_id") or "").strip()
        if not qid or qid in existing_ids:
            continue
        existing_ids.add(qid)

        q_type = str(payload.get("type") or payload.get("question_type") or "").strip()
        q_diff = str(payload.get("difficulty") or "").strip()
        q_knowledge = str(payload.get("knowledge_point") or "").strip()
        q_source_url = str(payload.get("source_url") or "").strip()

        stem = str(payload.get("stem") or "").strip() if store_stem else ""
        stem_fp = str(payload.get("stem_fingerprint") or payload.get("stem_fp") or "").strip() if store_stem else ""
        difficulty_value = payload.get("difficulty_value")
        quality_score = int(payload.get("quality_score") or 0)
        quality_flags = payload.get("quality_flags") or ""
        knowledge_points_json = payload.get("knowledge_points_json") or payload.get("knowledge_points") or ""
        source = str(payload.get("source") or "").strip()
        date = str(payload.get("date") or "").strip()

        answer = str(payload.get("answer") or payload.get("solution") or "").strip() if store_answer else ""
        analysis = str(payload.get("analysis") or payload.get("explanation") or "").strip() if store_analysis else ""
        cache_stem = str(payload.get("stem") or "").strip() if cache_store_stem else ""
        cache_stem_fp = (
            str(payload.get("stem_fingerprint") or payload.get("stem_fp") or "").strip() if cache_store_stem else ""
        )
        cache_answer = (
            str(payload.get("answer") or payload.get("solution") or "").strip() if cache_store_answer else ""
        )
        cache_analysis = (
            str(payload.get("analysis") or payload.get("explanation") or "").strip() if cache_store_analysis else ""
        )

        pq = PaperQuestion(
            user_id=uid,
            paper_id=pid,
            question_id=qid,
            question_order=max_order + appended + 1,
            question_type=q_type,
            difficulty=q_diff,
            knowledge_point=q_knowledge,
            source_url=q_source_url,
            stem=stem,
            stem_fingerprint=stem_fp,
            difficulty_value=difficulty_value,
            quality_score=quality_score,
            quality_flags=_to_json_str(quality_flags),
            knowledge_points_json=_to_json_str(knowledge_points_json),
            source=source,
            date=date,
            answer=answer,
            analysis=analysis,
        )
        session.add(pq)
        appended += 1

        cache_items.append(
            QuestionCache(
                question_id=qid,
                subject=str(payload.get("subject") or "").strip(),
                question_type=q_type,
                difficulty=q_diff,
                knowledge_point=q_knowledge,
                source_url=q_source_url,
                stem=cache_stem,
                stem_fingerprint=cache_stem_fp,
                answer=cache_answer,
                analysis=cache_analysis,
                difficulty_value=difficulty_value,
                quality_score=quality_score,
                quality_flags=_to_json_str(quality_flags),
                knowledge_points_json=_to_json_str(knowledge_points_json),
                source=source,
                date=date,
            )
        )

    for item in cache_items:
        if not _cache_item_has_content(item):
            continue
        try:
            await session.merge(item)
        except SQLAlchemyError:
            logger.exception("paper_question_cache_merge_failed")

    await session.flush()
    return appended


async def get_paper(
    *,
    user_id: str,
    paper_id: int,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_paper(user_id=uid, paper_id=paper_id, session=session)

    result = await session.execute(select(Paper).where(Paper.id == int(paper_id), Paper.user_id == uid))
    paper = result.scalar_one_or_none()
    if not paper:
        return None

    questions_result = await session.execute(
        select(PaperQuestion)
        .where(PaperQuestion.user_id == uid, PaperQuestion.paper_id == int(paper_id))
        .order_by(PaperQuestion.question_order)
    )
    questions = questions_result.scalars().all()

    return {
        "paper_id": paper.id,
        "user_id": paper.user_id,
        "paper_name": paper.paper_name,
        "created_at": paper.created_at.isoformat() if paper.created_at else "",
        "updated_at": paper.updated_at.isoformat() if paper.updated_at else "",
        "source_mode": _infer_paper_source_mode([str(q.question_id or "") for q in questions]),
        "questions": [
            {
                "question_id": q.question_id,
                "order": q.question_order,
                "type": q.question_type,
                "difficulty": q.difficulty,
                "difficulty_value": q.difficulty_value,
                "knowledge_point": q.knowledge_point,
                "knowledge_points_json": q.knowledge_points_json or "",
                "source_url": q.source_url,
                "stem": q.stem or "",
                "answer": q.answer or "",
                "analysis": q.analysis or "",
            }
            for q in questions
        ],
    }


async def list_papers(
    *,
    user_id: str,
    limit: int = 50,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_papers(user_id=uid, limit=limit, session=session)

    result = await session.execute(
        select(Paper)
        .options(selectinload(Paper.questions))
        .where(Paper.user_id == uid)
        .order_by(Paper.created_at.desc())
        .limit(int(limit or 50))
    )
    papers = result.scalars().all()
    return [
        {
            "paper_id": p.id,
            "user_id": p.user_id,
            "paper_name": p.paper_name,
            "created_at": p.created_at.isoformat() if p.created_at else "",
            "question_count": len(p.questions),
        }
        for p in papers
    ]


async def delete_paper(
    *,
    user_id: str,
    paper_id: int,
    session: Optional[AsyncSession] = None,
) -> bool:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await delete_paper(user_id=uid, paper_id=paper_id, session=session)
            await session.commit()
            return ok

    result = await session.execute(select(Paper).where(Paper.id == int(paper_id), Paper.user_id == uid))
    paper = result.scalar_one_or_none()
    if not paper:
        return False
    await session.delete(paper)
    await session.flush()
    return True
