from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from backend.database.repositories.content.study_archives import get_study_archive as db_get_study_archive
from backend.database.repositories.question.papers import get_paper as db_get_paper
from backend.shared.tasks import RuntimeTask, task_runtime
from backend.tasks.runners import (
    run_deepthink_task,
    run_export_paper_task,
    run_export_study_archive_task,
    run_generate_full_paper_task,
    run_knowledge_video_task,
    run_lesson_plan_task,
    run_paper_compose_task,
)


def _new_task_id(prefix: str) -> str:
    p = str(prefix or "").strip() or "task"
    return f"{p}-{uuid.uuid4().hex[:12]}"


def _clip_title(title: str, *, max_chars: int = 200) -> str:
    t = str(title or "").strip()
    if not t:
        return ""
    if max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    return t[:max_chars].rstrip()


async def submit_deepthink_task(*, user_id: str, request: Dict[str, Any], parent_task_id: Optional[str] = None) -> RuntimeTask:
    tid = _new_task_id("deepthink")
    subject = str((request or {}).get("subject") or "高中数学").strip() or "高中数学"
    title = _clip_title(f"深度解题：{subject}") or "深度解题"

    async def runner_factory(task: RuntimeTask) -> None:
        await run_deepthink_task(task, user_id=user_id)

    return await task_runtime.create_task(
        task_id=tid,
        user_id=user_id,
        task_type="deepthink",
        title=title,
        request=dict(request or {}),
        parent_task_id=str(parent_task_id or "").strip() or None,
        runner_factory=runner_factory,
        starter_event={"type": "step", "step": {"id": "task_started", "title": "开始深度解题", "status": "running"}},
    )


async def submit_lesson_plan_task(*, user_id: str, request: Dict[str, Any], parent_task_id: Optional[str] = None) -> RuntimeTask:
    tid = _new_task_id("lesson-plan")
    subject = str((request or {}).get("subject") or "").strip()
    grade = str((request or {}).get("grade") or "").strip()
    topic = str((request or {}).get("topic") or "").strip()
    title = _clip_title(f"教案：{subject} {grade}《{topic}》") or "教案生成"

    async def runner_factory(task: RuntimeTask) -> None:
        await run_lesson_plan_task(task, user_id=user_id)

    return await task_runtime.create_task(
        task_id=tid,
        user_id=user_id,
        task_type="lesson_plan",
        title=title,
        request=dict(request or {}),
        parent_task_id=str(parent_task_id or "").strip() or None,
        runner_factory=runner_factory,
        starter_event={"type": "step", "step": {"id": "task_started", "title": "开始生成教案", "status": "running"}},
    )


async def submit_paper_compose_task(
    *, user_id: str, request: Dict[str, Any], parent_task_id: Optional[str] = None
) -> RuntimeTask:
    req = dict(request or {})
    tid = str(req.get("taskId") or req.get("task_id") or "").strip() or _new_task_id("compose")
    req["taskId"] = tid

    title = _clip_title(str(req.get("paperName") or req.get("paper_name") or "组卷任务")) or "组卷任务"

    async def runner_factory(task: RuntimeTask) -> None:
        await run_paper_compose_task(task, user_id=user_id)

    return await task_runtime.create_task(
        task_id=tid,
        user_id=user_id,
        task_type="paper_compose",
        title=title,
        request=req,
        parent_task_id=str(parent_task_id or "").strip() or None,
        runner_factory=runner_factory,
    )


async def submit_generate_full_paper_task(
    *, user_id: str, request: Dict[str, Any], parent_task_id: Optional[str] = None
) -> RuntimeTask:
    req = dict(request or {})
    tid = str(req.get("taskId") or req.get("task_id") or "").strip() or _new_task_id("full-paper")
    req["taskId"] = tid

    subject = str(req.get("subject") or "").strip()
    topic = str(req.get("topic") or "").strip()
    title = _clip_title(f"一键出卷：{subject} {topic}") or "一键出卷"

    async def runner_factory(task: RuntimeTask) -> None:
        await run_generate_full_paper_task(task, user_id=user_id)

    return await task_runtime.create_task(
        task_id=tid,
        user_id=user_id,
        task_type="paper_generate_full",
        title=title,
        request=req,
        parent_task_id=str(parent_task_id or "").strip() or None,
        runner_factory=runner_factory,
    )


async def submit_export_paper_task(*, user_id: str, request: Dict[str, Any], parent_task_id: Optional[str] = None) -> RuntimeTask:
    tid = _new_task_id("export-paper")

    try:
        paper_id = int(request.get("paper_id") or request.get("paperId") or 0)
    except Exception:
        paper_id = 0

    paper = None
    if paper_id > 0:
        try:
            paper = await db_get_paper(user_id=user_id, paper_id=paper_id)
        except Exception:
            paper = None

    display = str((paper or {}).get("paper_name") or (paper or {}).get("name") or paper_id).strip() or str(paper_id)
    title = _clip_title(f"导出试卷：{display}") or "导出试卷"

    async def runner_factory(task: RuntimeTask) -> None:
        await run_export_paper_task(task, user_id=user_id)

    return await task_runtime.create_task(
        task_id=tid,
        user_id=user_id,
        task_type="export_paper",
        title=title,
        request=dict(request or {}),
        parent_task_id=str(parent_task_id or "").strip() or None,
        runner_factory=runner_factory,
    )


async def submit_export_study_archive_task(
    *, user_id: str, request: Dict[str, Any], parent_task_id: Optional[str] = None
) -> RuntimeTask:
    tid = _new_task_id("export-archive")

    try:
        archive_id = int(request.get("archive_id") or request.get("archiveId") or 0)
    except Exception:
        archive_id = 0

    archive = None
    if archive_id > 0:
        try:
            archive = await db_get_study_archive(user_id=user_id, archive_id=archive_id)
        except Exception:
            archive = None

    display = str((archive or {}).get("topic") or archive_id).strip() or str(archive_id)
    title = _clip_title(f"导出资料：{display}") or "导出资料"

    async def runner_factory(task: RuntimeTask) -> None:
        await run_export_study_archive_task(task, user_id=user_id)

    return await task_runtime.create_task(
        task_id=tid,
        user_id=user_id,
        task_type="export_study_archive",
        title=title,
        request=dict(request or {}),
        parent_task_id=str(parent_task_id or "").strip() or None,
        runner_factory=runner_factory,
    )


async def submit_knowledge_video_task(
    *, user_id: str, request: Dict[str, Any], parent_task_id: Optional[str] = None
) -> RuntimeTask:
    req = dict(request or {})
    tid = str(req.get("taskId") or req.get("task_id") or "").strip() or _new_task_id("knowledge-video")
    req["taskId"] = tid
    topic = str(req.get("topic") or req.get("query") or "").strip()
    title = _clip_title(f"知识视频：{topic}") or "知识视频生成"

    async def runner_factory(task: RuntimeTask) -> None:
        await run_knowledge_video_task(task, user_id=user_id)

    return await task_runtime.create_task(
        task_id=tid,
        user_id=user_id,
        task_type="knowledge_video",
        title=title,
        request=req,
        parent_task_id=str(parent_task_id or "").strip() or None,
        runner_factory=runner_factory,
        starter_event={"type": "step", "step": {"id": "task_started", "title": "开始生成知识视频", "status": "running"}},
    )
