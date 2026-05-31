"""Lesson plan API endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.lesson_plan_schemas import (
    LessonPlanCreateRequest,
    LessonPlanExportRequest,
    LessonPlanExportResponse,
    LessonPlanGenerateRequest,
    LessonPlanListResponse,
    LessonPlanResponse,
)
from backend.api.sse_utils import is_sse_client_disconnected
from backend.core.logging_utils import get_logger
from backend.generation.lesson_plan.store import (
    create_lesson_plan,
    delete_lesson_plan,
    export_lesson_plan_markdown,
    get_lesson_plan,
    list_lesson_plans,
)
from backend.shared.tasks import task_runtime
from backend.tasks import submit_lesson_plan_task

router = APIRouter(prefix="/lesson-plans", tags=["lesson-plans"], dependencies=[Depends(require_auth)])
logger = get_logger(__name__)


def _require_user_id(user: dict) -> str:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return user_id


@router.post("", response_model=LessonPlanResponse)
async def create_plan(
    request: LessonPlanCreateRequest,
    user: dict = Depends(require_auth),
):
    """Create a new lesson plan."""
    user_id = _require_user_id(user)
    plan = await create_lesson_plan(
        title=request.title,
        subject=request.subject,
        topic=request.topic,
        grade=request.grade,
        duration_minutes=request.duration_minutes,
        objectives=request.objectives,
        user_id=user_id,
    )
    return plan


@router.get("", response_model=LessonPlanListResponse)
async def list_plans(user: dict = Depends(require_auth)):
    """List all lesson plans owned by the current user."""
    user_id = _require_user_id(user)
    plans = await list_lesson_plans(user_id=user_id)
    return LessonPlanListResponse(plans=plans, total=len(plans))


@router.get("/{plan_id}", response_model=LessonPlanResponse)
async def get_plan(plan_id: str, user: dict = Depends(require_auth)):
    """Get a specific lesson plan owned by the current user."""
    user_id = _require_user_id(user)
    plan = await get_lesson_plan(plan_id, user_id=user_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Lesson plan not found")
    return plan


@router.delete("/{plan_id}")
async def delete_plan(plan_id: str, user: dict = Depends(require_auth)):
    """Delete a lesson plan owned by the current user."""
    user_id = _require_user_id(user)
    success = await delete_lesson_plan(plan_id, user_id=user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Lesson plan not found")
    return {"message": "Lesson plan deleted"}


@router.post("/generate")
async def generate_plan(
    request: LessonPlanGenerateRequest,
    http_request: Request,
    user: dict = Depends(require_auth),
):
    """Generate a lesson plan using AI with streaming response.

    NOTE:
    - `/api/tasks` is the canonical long-task API.
    - This endpoint is kept as a thin compatibility wrapper for older clients.
    """
    user_id = _require_user_id(user)

    task = await submit_lesson_plan_task(user_id=user_id, request=request.model_dump())

    async def event_generator():
        async for event in task_runtime.stream(task.task_id, after_seq=0, heartbeat_s=4.0):
            if await is_sse_client_disconnected(http_request):
                return
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Deprecated": "use /api/tasks/lesson-plans/generate",
        },
    )


@router.post("/export", response_model=LessonPlanExportResponse)
async def export_plan(request: LessonPlanExportRequest, user: dict = Depends(require_auth)):
    """Export a lesson plan to various formats (owner-scoped)."""
    user_id = _require_user_id(user)
    if request.format == "markdown":
        content = await export_lesson_plan_markdown(request.plan_id, user_id=user_id)
        if not content:
            raise HTTPException(status_code=404, detail="Lesson plan not found")
        return LessonPlanExportResponse(
            content=content,
            format="markdown",
            filename=f"lesson_plan_{request.plan_id}.md",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported export format: {request.format}",
        )
