"""Study materials streaming API endpoints.

This router supports **resumable** generation:
- `POST /api/study-materials/generate` starts a task and streams SSE events
- `GET  /api/study-materials/tasks/{task_id}/stream` can resume after refresh

Auth model: this is a local app — `require_auth` never rejects. Missing or
stale tokens fall back to the built-in local user (see `backend.api.auth`), so
handlers can rely on a non-empty `user_id` and intentionally carry no 401
branches.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.agent.executor import Executor
from backend.agent.types import CompressedContext, PlanStep, UserProfile
from backend.api.auth import require_auth
from backend.api.sse_utils import is_sse_client_disconnected
from backend.api.study_materials_schemas import (
    StudyMaterialsContinueRequest,
    StudyMaterialsConvertMarkdownToLatexRequest,
    StudyMaterialsConvertMarkdownToLatexResponse,
    StudyMaterialsGenerateRequest,
    build_study_materials_options,
    invalid_continue_mode_detail,
)
from backend.core.logging_utils import get_logger
from backend.generation.study_materials.orchestrator_singleton import study_material_tasks as _tasks

router = APIRouter(prefix="/study-materials", tags=["study-materials"], dependencies=[Depends(require_auth)])
logger = get_logger(__name__)



def _sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


async def _stream_task(task_id: str, *, user_id: str, after_seq: int, request: Request | None = None) -> StreamingResponse:
    heartbeat_s = float(os.getenv("STUDY_MATERIALS_SSE_HEARTBEAT_S") or "4.0")

    async def event_generator():
        async for event in _tasks.stream(task_id, user_id=user_id, after_seq=after_seq, heartbeat_s=heartbeat_s):
            if request is not None and await is_sse_client_disconnected(request):
                return
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@router.post("/generate")
async def generate_study_materials(
    request: StudyMaterialsGenerateRequest,
    http_request: Request,
    user: dict = Depends(require_auth),
):
    """Start a new study-materials generation task and stream events."""

    user_id = str((user or {}).get("user_id") or "").strip()

    query = (request.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty query")

    subject = (request.subject or "").strip()
    options = build_study_materials_options(request)

    task = await _tasks.create_task(query=query, user_id=user_id, subject=subject, options=options)
    response = await _stream_task(task.task_id, user_id=user_id, after_seq=0, request=http_request)
    # POST-as-stream creates the task id server-side; expose it so clients can
    # re-attach via GET /tasks/{task_id}/stream without parsing the event flow.
    response.headers["X-Task-Id"] = task.task_id
    return response


@router.post("/convert-markdown-to-latex", response_model=StudyMaterialsConvertMarkdownToLatexResponse)
async def convert_markdown_to_latex(
    request: StudyMaterialsConvertMarkdownToLatexRequest,
    user: dict = Depends(require_auth),
):
    user_id = str((user or {}).get("user_id") or "").strip()

    markdown = (request.markdown or "").strip()
    if not markdown:
        raise HTTPException(status_code=400, detail="markdown_empty")

    topic = (request.topic or "").strip()
    subject = (request.subject or "").strip()

    profile = UserProfile(user_id=user_id)
    if subject:
        profile.preferences["subject"] = subject

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
        logger.exception("convert_markdown_to_latex_failed", extra={"user_id": user_id})
        raise HTTPException(status_code=500, detail="convert_markdown_to_latex_failed") from exc


@router.post("/convert-markdown-to-latex/stream")
async def convert_markdown_to_latex_stream(
    request: StudyMaterialsConvertMarkdownToLatexRequest,
    http_request: Request,
    user: dict = Depends(require_auth),
):
    user_id = str((user or {}).get("user_id") or "").strip()

    markdown = (request.markdown or "").strip()
    if not markdown:
        raise HTTPException(status_code=400, detail="markdown_empty")

    topic = (request.topic or "").strip()
    subject = (request.subject or "").strip()

    profile = UserProfile(user_id=user_id)
    if subject:
        profile.preferences["subject"] = subject

    ctx = CompressedContext(
        user_profile=profile,
        system_instructions="",
        current_task=topic or "study_archive",
    )

    executor = Executor()
    heartbeat_s = float(os.getenv("STUDY_MATERIALS_SSE_HEARTBEAT_S") or "4.0")

    async def event_generator():
        # Standard task-stream envelope (same convention as `_stream_task` /
        # `orchestrator.stream`): {taskId, seq, type, data} frames, a ping
        # heartbeat while the tool runs, and a terminal `data: [DONE]` marker.
        step_id = f"convert_markdown_to_latex-{uuid.uuid4().hex[:8]}"
        stream_id = step_id
        t0 = time.monotonic()
        seq = 0

        def frame(kind: str, data: dict) -> str:
            nonlocal seq
            seq += 1
            payload = {"taskId": stream_id, "seq": seq, "type": kind, "data": data}
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        def ping_frame() -> str:
            # Heartbeats do not advance the sequence (matches task-runtime pings).
            payload = {"taskId": stream_id, "seq": seq, "type": "ping", "data": {"status": "running", "last_seq": seq}}
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        try:
            if await is_sse_client_disconnected(http_request):
                return
            yield frame("status", {"content": "开始转换 LaTeX…"})
            if await is_sse_client_disconnected(http_request):
                return
            yield frame("progress", {"percent": 1, "stage": "准备"})
            if await is_sse_client_disconnected(http_request):
                return
            yield frame("tool_call", {"step_id": step_id, "name": "convert_markdown_to_latex", "title": "Markdown → LaTeX（ElegantBook）", "arguments": {"topic": topic, "subject": subject}})

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
                    timeout=max(0.5, float(heartbeat_s or 4.0)),
                )

                if not done:
                    # Heartbeat tick while the tool call is still in flight.
                    if await is_sse_client_disconnected(http_request):
                        return
                    yield ping_frame()
                    continue

                if queue_task in done:
                    evt = None
                    try:
                        evt = queue_task.result()
                    except asyncio.CancelledError:
                        evt = None
                    if isinstance(evt, dict) and evt.get("event"):
                        if await is_sse_client_disconnected(http_request):
                            return
                        yield frame(
                            str(evt.get("event") or ""),
                            evt.get("data") if isinstance(evt.get("data"), dict) else {},
                        )
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
                        yield frame(
                            str(evt.get("event") or ""),
                            evt.get("data") if isinstance(evt.get("data"), dict) else {},
                        )
            except asyncio.QueueEmpty:
                pass

            step_result = await tool_task
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            if await is_sse_client_disconnected(http_request):
                return
            yield frame("tool_result", {"step_id": step_id, "name": "convert_markdown_to_latex", "title": "Markdown → LaTeX（ElegantBook）", "success": bool(step_result.success), "elapsed_ms": elapsed_ms, "output": step_result.output, "error": step_result.error})

            if not step_result.success:
                msg = str(step_result.error or "convert_failed")
                if await is_sse_client_disconnected(http_request):
                    return
                yield frame("error", {"message": msg})
            else:
                out = step_result.output if isinstance(step_result.output, dict) else {}
                if await is_sse_client_disconnected(http_request):
                    return
                yield frame("progress", {"percent": 100, "stage": "完成"})
                if await is_sse_client_disconnected(http_request):
                    return
                yield frame("done", out)
        except Exception as exc:
            logger.exception("study_materials_latex_stream_failed")
            if await is_sse_client_disconnected(http_request):
                return
            yield frame("error", {"message": str(exc)})

        # Terminal marker (matches the chat-stream `data: [DONE]` convention).
        if await is_sse_client_disconnected(http_request):
            return
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@router.get("/tasks/{task_id}/stream")
async def stream_study_materials_task(
    task_id: str,
    request: Request,
    after_seq: int = Query(0, ge=0),
    user: dict = Depends(require_auth),
):
    """Resume a running/completed task and replay SSE events after `after_seq`."""

    user_id = str((user or {}).get("user_id") or "").strip()

    task = await _tasks.get_task(task_id, user_id=user_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return await _stream_task(task.task_id, user_id=user_id, after_seq=after_seq, request=request)


@router.get("/tasks/{task_id}")
async def get_study_materials_task(task_id: str, user: dict = Depends(require_auth)):
    user_id = str((user or {}).get("user_id") or "").strip()

    task = await _tasks.get_task(task_id, user_id=user_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Backward-compatible seq handling:
    # - New orchestrator view exposes `first_seq` directly.
    # - Older runtime tasks expose `seq_offset` (first_seq = seq_offset + 1).
    first_seq = getattr(task, "first_seq", None)
    if first_seq is None:
        seq_offset = getattr(task, "seq_offset", 0)
        try:
            first_seq = int(seq_offset) + 1
        except (TypeError, ValueError):
            first_seq = 1
    else:
        try:
            first_seq = int(first_seq)
        except (TypeError, ValueError):
            first_seq = 1

    wm = getattr(task, "resume_working_memory", None)
    wm_dict = wm if isinstance(wm, dict) else {}
    workflow = wm_dict.get("study_materials_workflow")
    workflow = workflow if isinstance(workflow, dict) else {}
    last_failure = workflow.get("last_failure")
    last_failure = last_failure if isinstance(last_failure, dict) else {}
    task_status = str(task.status or "").lower()

    # continue_task only requires a non-empty working-memory snapshot. Staged
    # workflows can resume from plan/research/draft before markdown exists.
    resumable = bool(wm_dict and task_status != "running")
    recovery_available = bool(
        resumable
        and task_status == "failed"
        and last_failure.get("recoverable") is not False
    )
    workflow_failed_stage = str(last_failure.get("stage") or "").strip()
    if not workflow_failed_stage and task_status == "failed":
        candidate_stage = str(workflow.get("stage") or "").strip()
        if candidate_stage in {"plan", "research", "draft", "review", "revise", "accept"}:
            workflow_failed_stage = candidate_stage
    last_failed_stage = workflow_failed_stage or str(task.last_failed_stage or "").strip()

    return {
        "task_id": task.task_id,
        "query": task.query,
        "user_id": task.user_id,
        "status": task.status,
        "error": task.error,
        "created_at_s": task.created_at_s,
        "updated_at_s": task.updated_at_s,
        "first_seq": first_seq,
        "last_seq": task.last_seq,
        "resumable": resumable,
        "recovery_available": recovery_available,
        "last_success_step": task.last_success_step,
        "last_failed_step": task.last_failed_step,
        "last_success_stage": task.last_success_stage,
        "last_failed_stage": last_failed_stage,
        "per_kp_state": task.per_kp_state,
        "search_summary_by_kp": task.search_summary_by_kp,
    }


@router.post("/tasks/{task_id}/continue")
async def continue_study_materials_task(
    task_id: str,
    request: StudyMaterialsContinueRequest,
    http_request: Request,
    user: dict = Depends(require_auth),
):
    """Continue a completed/failed task with one bounded improvement iteration (streams SSE events)."""

    user_id = str((user or {}).get("user_id") or "").strip()
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
        if msg == "invalid_continue_mode":
            raise HTTPException(status_code=400, detail=invalid_continue_mode_detail(mode))
        raise HTTPException(status_code=400, detail=msg)

    response = await _stream_task(new_task.task_id, user_id=user_id, after_seq=0, request=http_request)
    # POST-as-stream: the follow-up task id is otherwise only visible in-stream.
    response.headers["X-Task-Id"] = new_task.task_id
    return response
