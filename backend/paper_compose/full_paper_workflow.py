from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncIterator, Dict, List

from sqlalchemy.exc import SQLAlchemyError

from backend.core.logging_utils import get_logger
from backend.core.subjects import resolve_subject
from backend.database.repositories.content.study_archives import get_latest_study_archive
from backend.database.repositories.question.papers import save_paper
from backend.database.repositories.question.question_cache import upsert_question_cache
from backend.paper_compose.ai_fill import fill_slot_with_ai
from backend.paper_compose.auto_planner import plan_exam_structure
from backend.question_library.gen_utils import ReasoningEventHandler

logger = get_logger(__name__)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


async def generate_full_paper_events(
    request: Dict[str, Any],
    *,
    user_id: str,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> AsyncIterator[Dict[str, Any]]:
    """One-click full paper generation workflow (SSE events)."""

    req = dict(request or {})
    task_id = str(req.get("taskId") or req.get("task_id") or "").strip() or uuid.uuid4().hex[:12]

    subject_input = str(req.get("subject") or "").strip()
    topic = str(req.get("topic") or "").strip() or "相关知识点"
    paper_name = str(req.get("paperName") or req.get("paper_name") or "").strip()

    total_points = _as_int(req.get("total_points") or req.get("totalPoints") or 150, 150)
    time_limit = _as_int(req.get("time_limit") or req.get("timeLimit") or 120, 120)
    difficulty_distribution = req.get("difficulty_distribution") or req.get("difficultyDistribution") or {}

    use_archive = bool(req.get("useStudyArchive")) if "useStudyArchive" in req else bool(req.get("use_study_archive"))

    if not subject_input:
        yield {"type": "error", "error": "missing_subject", "taskId": task_id}
        return

    try:
        subject = resolve_subject(subject_input, strict=True)
    except ValueError as exc:
        yield {"type": "error", "error": "invalid_subject", "taskId": task_id, "data": {"detail": str(exc)}}
        return

    if not paper_name:
        paper_name = f"{subject}-{topic}-试卷"

    yield {"type": "progress", "progress": 1.0}

    # 1) Plan structure
    yield {
        "type": "step",
        "step": {
            "id": "plan_structure",
            "title": "规划试卷结构",
            "status": "running",
            "startTime": _now_iso(),
            "toolName": "generate_full_paper",
            "input": {
                "subject": subject,
                "topic": topic,
                "total_points": total_points,
                "time_limit": time_limit,
                "difficulty_distribution": difficulty_distribution,
            },
        },
    }

    structure = await plan_exam_structure(
        subject=subject,
        topic=topic,
        total_points=total_points,
        time_limit=time_limit,
        difficulty_distribution=difficulty_distribution if isinstance(difficulty_distribution, dict) else None,
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    slots = structure.get("slots") if isinstance(structure, dict) else None
    if not isinstance(slots, list) or not slots:
        yield {"type": "error", "error": "plan_structure_failed", "taskId": task_id}
        return

    yield {
        "type": "step",
        "step": {
            "id": "plan_structure",
            "title": "规划试卷结构",
            "status": "completed",
            "startTime": _now_iso(),
            "endTime": _now_iso(),
            "toolName": "generate_full_paper",
            "output": {"slotCount": len(slots), "slots": slots[:12]},
        },
    }
    yield {"type": "progress", "progress": 10.0}

    # 2) Build source pack (optional: from latest study archive)
    yield {
        "type": "step",
        "step": {
            "id": "build_source_pack",
            "title": "构建素材包",
            "status": "running",
            "startTime": _now_iso(),
            "toolName": "generate_full_paper",
            "input": {"useStudyArchive": bool(use_archive)},
        },
    }

    study_markdown = ""
    if use_archive:
        try:
            archive = await get_latest_study_archive(user_id=str(user_id or "").strip(), subject=subject, topic=topic)
        except (SQLAlchemyError, ValueError):
            archive = None
        if isinstance(archive, dict):
            study_markdown = str(archive.get("markdown") or "")

    # Keep source_pack light here; question_library will enrich when needed.
    source_pack = {"subject": subject, "topic": topic, "study_markdown": study_markdown}

    yield {
        "type": "step",
        "step": {
            "id": "build_source_pack",
            "title": "构建素材包",
            "status": "completed",
            "startTime": _now_iso(),
            "endTime": _now_iso(),
            "toolName": "generate_full_paper",
            "output": {"study_markdown_chars": len(study_markdown)},
        },
    }
    yield {"type": "progress", "progress": 18.0}

    # 3) Fill slots with AI (parallel, bounded)
    yield {
        "type": "step",
        "step": {
            "id": "fill_slots",
            "title": "AI 填充题目",
            "status": "running",
            "startTime": _now_iso(),
            "toolName": "generate_full_paper",
            "input": {"slotCount": len(slots)},
        },
    }

    sem = asyncio.Semaphore(3)
    filled: List[dict] = []

    async def _fill_one(slot_index: int, slot: dict) -> List[dict]:
        async with sem:
            return await fill_slot_with_ai(
                source_pack=source_pack,
                subject=subject,
                topic=topic,
                slot=slot,
                user_id=str(user_id or "").strip(),
                slot_index=slot_index,
                stream_reasoning=stream_reasoning,
                on_reasoning_event=on_reasoning_event,
                fallback_to_crawler=True,
            )

    tasks = [_fill_one(i, s if isinstance(s, dict) else {}) for i, s in enumerate(slots)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    filled_slots = 0
    for slot, res in zip(slots, results):
        if isinstance(res, Exception):
            continue
        if not isinstance(res, list):
            continue
        if res:
            filled_slots += 1
        points_each = (slot or {}).get("points_each") if isinstance(slot, dict) else None
        for item in res:
            if not isinstance(item, dict):
                continue
            it = dict(item)
            if points_each is not None and "points" not in it:
                it["points"] = points_each
            filled.append(it)

    # Ensure order field for export/UI.
    for idx, q in enumerate(filled):
        q.setdefault("order", idx + 1)

    yield {"type": "progress", "progress": 60.0}
    yield {
        "type": "step",
        "step": {
            "id": "fill_slots",
            "title": "AI 填充题目",
            "status": "completed",
            "startTime": _now_iso(),
            "endTime": _now_iso(),
            "toolName": "generate_full_paper",
            "output": {"filled_slots": filled_slots, "question_count": len(filled)},
        },
    }

    if not filled:
        yield {"type": "error", "error": "no_questions_generated", "taskId": task_id}
        return

    # 4) Diagram enhancement (already embedded in question_library pipeline; keep as explicit stage).
    yield {
        "type": "step",
        "step": {
            "id": "diagram_enhance",
            "title": "配图增强",
            "status": "running",
            "startTime": _now_iso(),
            "toolName": "generate_full_paper",
        },
    }
    diagram_count = 0
    for q in filled:
        diagrams = q.get("diagrams")
        if isinstance(diagrams, list):
            diagram_count += len([d for d in diagrams if isinstance(d, dict)])
    yield {
        "type": "step",
        "step": {
            "id": "diagram_enhance",
            "title": "配图增强",
            "status": "completed",
            "startTime": _now_iso(),
            "endTime": _now_iso(),
            "toolName": "generate_full_paper",
            "output": {"diagram_count": diagram_count},
        },
    }
    yield {"type": "progress", "progress": 68.0}

    # 5) Balance check (lightweight for now).
    yield {
        "type": "step",
        "step": {
            "id": "balance_check",
            "title": "平衡检查",
            "status": "running",
            "startTime": _now_iso(),
            "toolName": "generate_full_paper",
        },
    }
    type_counts: Dict[str, int] = {}
    for q in filled:
        t = str(q.get("type") or q.get("question_type") or "").strip() or "其他题"
        type_counts[t] = type_counts.get(t, 0) + 1
    yield {
        "type": "step",
        "step": {
            "id": "balance_check",
            "title": "平衡检查",
            "status": "completed",
            "startTime": _now_iso(),
            "endTime": _now_iso(),
            "toolName": "generate_full_paper",
            "output": {"question_count": len(filled), "type_counts": type_counts},
        },
    }
    yield {"type": "progress", "progress": 76.0}

    # 6) Save (cache questions + persist paper).
    yield {
        "type": "step",
        "step": {
            "id": "save",
            "title": "保存试卷",
            "status": "running",
            "startTime": _now_iso(),
            "toolName": "generate_full_paper",
        },
    }

    try:
        await upsert_question_cache(
            [
                {
                    "question_id": str(q.get("question_id") or "").strip(),
                    "subject": subject,
                    "question_type": str(q.get("type") or q.get("question_type") or "").strip(),
                    "difficulty": str(q.get("difficulty") or "").strip(),
                    "knowledge_point": str(q.get("knowledge_point") or topic).strip(),
                    "source_url": str(q.get("source_url") or "").strip(),
                    "stem": str(q.get("stem") or "").strip(),
                    "answer": str(q.get("answer") or "").strip(),
                    "analysis": str(q.get("analysis") or "").strip(),
                    "source": str(q.get("source") or "ai_generate_full").strip(),
                }
                for q in filled
                if isinstance(q, dict) and str(q.get("question_id") or "").strip()
            ]
        )
    except (SQLAlchemyError, TypeError, ValueError):
        logger.warning("generate_full_paper_upsert_cache_failed", exc_info=True, extra={"task_id": task_id})

    try:
        paper_id = await save_paper(user_id=str(user_id or "").strip(), paper_name=paper_name, questions=filled)
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        yield {"type": "error", "error": "paper_save_failed", "taskId": task_id, "data": {"detail": str(exc)}}
        return

    yield {
        "type": "step",
        "step": {
            "id": "save",
            "title": "保存试卷",
            "status": "completed",
            "startTime": _now_iso(),
            "endTime": _now_iso(),
            "toolName": "generate_full_paper",
            "output": {"paper_id": int(paper_id), "paper_name": paper_name, "question_count": len(filled)},
        },
    }
    yield {"type": "progress", "progress": 100.0}
    yield {
        "type": "result",
        "result": {
            "paper_id": int(paper_id),
            "paper_name": paper_name,
            "subject": subject,
            "topic": topic,
            "question_count": len(filled),
            "slots": slots,
        },
    }
