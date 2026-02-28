"""Study materials streaming API endpoints.

This router supports **resumable** generation:
- `POST /api/study-materials/generate` starts a task and streams SSE events
- `GET  /api/study-materials/tasks/{task_id}/stream` can resume after refresh
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.agent.executor import Executor
from backend.agent.types import CompressedContext, PlanStep, UserProfile, agent_event
from backend.api.auth import get_current_user, require_auth
from backend.api.study_materials_schemas import (
    StudyMaterialsConvertMarkdownToLatexRequest,
    StudyMaterialsConvertMarkdownToLatexResponse,
    StudyMaterialsContinueRequest,
    StudyMaterialsGenerateRequest,
)
from backend.study_materials.task_manager import StudyMaterialsTaskManager


router = APIRouter(prefix="/study-materials", tags=["study-materials"], dependencies=[Depends(require_auth)])

_tasks = StudyMaterialsTaskManager(
    max_tasks=int(os.getenv("STUDY_MATERIALS_MAX_TASKS") or "50"),
    task_ttl_s=int(os.getenv("STUDY_MATERIALS_TASK_TTL_S") or str(60 * 60)),
    max_events_per_task=int(os.getenv("STUDY_MATERIALS_TASK_MAX_EVENTS") or "8000"),
)


def _env_truthy(name: str) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _clip_text(text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    t = (text or "")
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def _sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


async def _stream_task(task_id: str, *, after_seq: int) -> StreamingResponse:
    heartbeat_s = float(os.getenv("STUDY_MATERIALS_SSE_HEARTBEAT_S") or "4.0")

    async def event_generator():
        async for event in _tasks.stream(task_id, after_seq=after_seq, heartbeat_s=heartbeat_s):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@router.post("/generate")
async def generate_study_materials(
    request: StudyMaterialsGenerateRequest,
    user: Optional[dict] = Depends(get_current_user),
):
    """Start a new study-materials generation task and stream events."""

    user_id = (user.get("user_id") if user else None) or "anonymous"

    query = (request.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty query")

    subject = (request.subject or "").strip()
    options = {}
    if (request.preset or "").strip():
        options["preset"] = str(request.preset or "").strip()
    if (request.requirements or "").strip():
        options["requirements"] = _clip_text(str(request.requirements or "").strip(), max_chars=600)
    if request.with_questions is not None:
        options["with_questions"] = bool(request.with_questions)
    if request.with_diagrams is not None:
        options["with_diagrams"] = bool(request.with_diagrams)
    if request.enable_extra_tools is not None:
        options["enable_extra_tools"] = bool(request.enable_extra_tools)
    if request.max_points is not None:
        try:
            n = int(request.max_points)
        except Exception:
            n = 0
        if n > 0:
            options["max_points"] = max(1, min(n, 15))

    task = await _tasks.create_task(query=query, user_id=user_id, subject=subject, options=options)
    return await _stream_task(task.task_id, after_seq=0)


@router.post("/convert-markdown-to-latex", response_model=StudyMaterialsConvertMarkdownToLatexResponse)
async def convert_markdown_to_latex(
    request: StudyMaterialsConvertMarkdownToLatexRequest,
    user: Optional[dict] = Depends(get_current_user),
):
    user_id = (user.get("user_id") if user else None) or "anonymous"

    markdown = (request.markdown or "").strip()
    if not markdown:
        raise HTTPException(status_code=400, detail="markdown_empty")

    topic = (request.topic or "").strip()
    subject = (request.subject or "").strip()

    profile = UserProfile(user_id=user_id)
    if subject:
        try:
            profile.preferences["subject"] = subject
        except Exception:
            pass

    ctx = CompressedContext(
        user_profile=profile,
        system_instructions="",
        current_task=topic or "study_archive",
    )

    executor = Executor()
    try:
        return await executor._tool_convert_markdown_to_latex(
            {"markdown": markdown, "topic": topic, "subject": subject},
            ctx,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/convert-markdown-to-latex/stream")
async def convert_markdown_to_latex_stream(
    request: StudyMaterialsConvertMarkdownToLatexRequest,
    user: Optional[dict] = Depends(get_current_user),
):
    user_id = (user.get("user_id") if user else None) or "anonymous"

    markdown = (request.markdown or "").strip()
    if not markdown:
        raise HTTPException(status_code=400, detail="markdown_empty")

    topic = (request.topic or "").strip()
    subject = (request.subject or "").strip()

    profile = UserProfile(user_id=user_id)
    if subject:
        try:
            profile.preferences["subject"] = subject
        except Exception:
            pass

    ctx = CompressedContext(
        user_profile=profile,
        system_instructions="",
        current_task=topic or "study_archive",
    )

    executor = Executor()

    async def event_generator():
        step_id = f"convert_markdown_to_latex-{uuid.uuid4().hex[:8]}"
        t0 = time.monotonic()

        try:
            yield f"data: {json.dumps(agent_event('status', {'content': '开始转换 LaTeX…'}), ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps(agent_event('progress', {'percent': 1, 'stage': '准备'}), ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps(agent_event('tool_call', {'step_id': step_id, 'name': 'convert_markdown_to_latex', 'title': 'Markdown → LaTeX（ElegantBook）', 'arguments': {'topic': topic, 'subject': subject}}), ensure_ascii=False)}\n\n"

            event_queue: "asyncio.Queue[dict]" = asyncio.Queue()

            async def emit(evt: dict) -> None:
                if not isinstance(evt, dict):
                    return
                kind = str(evt.get("event") or "")
                if kind in {"status", "progress"}:
                    await event_queue.put(evt)

            step = PlanStep(
                id=step_id,
                title="Markdown → LaTeX（ElegantBook）",
                tool="convert_markdown_to_latex",
                arguments={"markdown": markdown, "topic": topic, "subject": subject},
            )

            tool_task = asyncio.create_task(executor.execute_step(step, context=ctx, emit_event=emit))
            queue_task: "asyncio.Task[dict]" = asyncio.create_task(event_queue.get())

            while True:
                done, _pending = await asyncio.wait(
                    {tool_task, queue_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if queue_task in done:
                    evt = None
                    try:
                        evt = queue_task.result()
                    except Exception:
                        evt = None
                    if isinstance(evt, dict) and evt.get("event"):
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                    queue_task = asyncio.create_task(event_queue.get())
                    continue

                if tool_task in done:
                    if not queue_task.done():
                        queue_task.cancel()
                    break

            try:
                while True:
                    evt = event_queue.get_nowait()
                    if isinstance(evt, dict) and evt.get("event"):
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            except Exception:
                pass

            step_result = await tool_task
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            yield f"data: {json.dumps(agent_event('tool_result', {'step_id': step_id, 'name': 'convert_markdown_to_latex', 'title': 'Markdown → LaTeX（ElegantBook）', 'success': bool(step_result.success), 'elapsed_ms': elapsed_ms, 'output': step_result.output, 'error': step_result.error}), ensure_ascii=False)}\n\n"

            if not step_result.success:
                msg = str(step_result.error or "convert_failed")
                yield f"data: {json.dumps(agent_event('error', {'message': msg}), ensure_ascii=False)}\n\n"
                return

            out = step_result.output if isinstance(step_result.output, dict) else {}
            yield f"data: {json.dumps(agent_event('progress', {'percent': 100, 'stage': '完成'}), ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps(agent_event('done', out), ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps(agent_event('error', {'message': str(exc)}), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@router.get("/tasks/{task_id}/stream")
async def stream_study_materials_task(
    task_id: str,
    after_seq: int = Query(0, ge=0),
):
    """Resume a running/completed task and replay SSE events after `after_seq`."""

    task = await _tasks.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return await _stream_task(task.task_id, after_seq=after_seq)


@router.get("/tasks/{task_id}")
async def get_study_materials_task(task_id: str):
    task = await _tasks.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task.task_id,
        "query": task.query,
        "user_id": task.user_id,
        "status": task.status,
        "error": task.error,
        "created_at_s": task.created_at_s,
        "updated_at_s": task.updated_at_s,
        "first_seq": task.seq_offset + 1,
        "last_seq": task.last_seq,
    }


@router.post("/tasks/{task_id}/continue")
async def continue_study_materials_task(
    task_id: str,
    request: StudyMaterialsContinueRequest,
    user: Optional[dict] = Depends(get_current_user),
):
    """Continue a completed/failed task with one bounded improvement iteration (streams SSE events)."""

    user_id = (user.get("user_id") if user else None) or "anonymous"
    mode = str(request.mode or "").strip() or "improve"

    try:
        new_task = await _tasks.continue_task(task_id=task_id, user_id=user_id, mode=mode)
    except ValueError as exc:
        msg = str(exc)
        if msg == "task_not_found":
            raise HTTPException(status_code=404, detail="Task not found")
        if msg == "task_running":
            raise HTTPException(status_code=409, detail="Task still running")
        if msg == "task_not_resumable":
            raise HTTPException(status_code=400, detail="Task not resumable")
        raise HTTPException(status_code=400, detail=msg)

    return await _stream_task(new_task.task_id, after_seq=0)
