from __future__ import annotations

import json
from typing import Any, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from backend.database.engine import async_session_maker
from backend.database.schema import Paper, PaperQuestion, QuestionCache


def _to_json_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) or isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return ""
    return ""


async def save_paper(*, paper_name: str, questions: List[dict]) -> int:
    """保存试卷并写入题目快照（以及本地题目缓存）。"""

    async with async_session_maker() as session:
        paper = Paper(paper_name=str(paper_name or "").strip() or "未命名试卷")
        session.add(paper)
        await session.commit()
        await session.refresh(paper)

        cache_items: List[QuestionCache] = []

        for i, q_data in enumerate(questions or []):
            if isinstance(q_data, str):
                payload: dict = {"question_id": q_data}
            else:
                payload = dict(q_data or {})

            qid = str(payload.get("question_id") or "").strip()
            q_type = str(payload.get("type") or payload.get("question_type") or "").strip()
            q_diff = str(payload.get("difficulty") or "").strip()
            q_knowledge = str(payload.get("knowledge_point") or "").strip()
            q_source_url = str(payload.get("source_url") or "").strip()

            stem = str(payload.get("stem") or "").strip()
            stem_fp = str(payload.get("stem_fingerprint") or payload.get("stem_fp") or "").strip()
            difficulty_value = payload.get("difficulty_value")
            quality_score = int(payload.get("quality_score") or 0)
            quality_flags = payload.get("quality_flags") or ""
            knowledge_points_json = payload.get("knowledge_points_json") or payload.get("knowledge_points") or ""
            source = str(payload.get("source") or "").strip()
            date = str(payload.get("date") or "").strip()

            answer = str(payload.get("answer") or payload.get("solution") or "").strip()
            analysis = str(payload.get("analysis") or payload.get("explanation") or "").strip()

            pq = PaperQuestion(
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
                        stem=stem,
                        stem_fingerprint=stem_fp,
                        answer=answer,
                        analysis=analysis,
                        difficulty_value=difficulty_value,
                        quality_score=quality_score,
                        quality_flags=_to_json_str(quality_flags),
                        knowledge_points_json=_to_json_str(knowledge_points_json),
                        source=source,
                        date=date,
                    )
                )

        # Upsert cache entries (best-effort). SQLite supports INSERT OR REPLACE for PK rows.
        for item in cache_items:
            try:
                await session.merge(item)
            except Exception:
                pass

        await session.commit()
        return int(paper.id)


async def add_questions_to_paper(*, paper_id: int, questions: List[dict]) -> int:
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

    async with async_session_maker() as session:
        result = await session.execute(select(Paper).where(Paper.id == pid))
        paper = result.scalar_one_or_none()
        if not paper:
            raise ValueError("paper_not_found")

        max_order_res = await session.execute(
            select(func.max(PaperQuestion.question_order)).where(PaperQuestion.paper_id == pid)
        )
        max_order = int(max_order_res.scalar() or 0)

        existing_ids_res = await session.execute(
            select(PaperQuestion.question_id).where(PaperQuestion.paper_id == pid)
        )
        existing_ids = {str(x).strip() for x in existing_ids_res.scalars().all() if str(x or "").strip()}

        cache_items: List[QuestionCache] = []
        appended = 0

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

            stem = str(payload.get("stem") or "").strip()
            stem_fp = str(payload.get("stem_fingerprint") or payload.get("stem_fp") or "").strip()
            difficulty_value = payload.get("difficulty_value")
            quality_score = int(payload.get("quality_score") or 0)
            quality_flags = payload.get("quality_flags") or ""
            knowledge_points_json = payload.get("knowledge_points_json") or payload.get("knowledge_points") or ""
            source = str(payload.get("source") or "").strip()
            date = str(payload.get("date") or "").strip()

            answer = str(payload.get("answer") or payload.get("solution") or "").strip()
            analysis = str(payload.get("analysis") or payload.get("explanation") or "").strip()

            pq = PaperQuestion(
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
                    stem=stem,
                    stem_fingerprint=stem_fp,
                    answer=answer,
                    analysis=analysis,
                    difficulty_value=difficulty_value,
                    quality_score=quality_score,
                    quality_flags=_to_json_str(quality_flags),
                    knowledge_points_json=_to_json_str(knowledge_points_json),
                    source=source,
                    date=date,
                )
            )

        for item in cache_items:
            try:
                await session.merge(item)
            except Exception:
                pass

        await session.commit()
        return appended


async def get_paper(paper_id: int) -> Optional[dict]:
    async with async_session_maker() as session:
        result = await session.execute(select(Paper).where(Paper.id == int(paper_id)))
        paper = result.scalar_one_or_none()
        if not paper:
            return None

        questions_result = await session.execute(
            select(PaperQuestion)
            .where(PaperQuestion.paper_id == int(paper_id))
            .order_by(PaperQuestion.question_order)
        )
        questions = questions_result.scalars().all()

        return {
            "paper_id": paper.id,
            "paper_name": paper.paper_name,
            "created_at": paper.created_at.isoformat() if paper.created_at else "",
            "updated_at": paper.updated_at.isoformat() if paper.updated_at else "",
            "questions": [
                {
                    "question_id": q.question_id,
                    "order": q.question_order,
                    "type": q.question_type,
                    "difficulty": q.difficulty,
                    "knowledge_point": q.knowledge_point,
                    "source_url": q.source_url,
                    "stem": q.stem or "",
                    "answer": q.answer or "",
                    "analysis": q.analysis or "",
                }
                for q in questions
            ],
        }


async def list_papers(*, limit: int = 50) -> List[dict]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Paper)
            .options(selectinload(Paper.questions))
            .order_by(Paper.created_at.desc())
            .limit(int(limit or 50))
        )
        papers = result.scalars().all()
        return [
            {
                "paper_id": p.id,
                "paper_name": p.paper_name,
                "created_at": p.created_at.isoformat() if p.created_at else "",
                "question_count": len(p.questions),
            }
            for p in papers
        ]


async def delete_paper(paper_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(select(Paper).where(Paper.id == int(paper_id)))
        paper = result.scalar_one_or_none()
        if not paper:
            return False
        await session.delete(paper)
        await session.commit()
        return True
