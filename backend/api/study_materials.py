"""Study materials streaming API endpoints.

This router supports **resumable** generation:
- `POST /api/study-materials/generate` starts a task and streams SSE events
- `GET  /api/study-materials/tasks/{task_id}/stream` can resume after refresh
"""

from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.api.auth import get_current_user, require_auth
from backend.api.study_materials_schemas import StudyMaterialsGenerateRequest
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

