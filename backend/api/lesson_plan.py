"""Lesson plan API endpoints."""

from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
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
from backend.core.logging_utils import get_logger
from backend.core.time_utils import utcnow_iso_z, utcnow_naive
from backend.database.repositories.tasks import append_task_event as db_append_task_event
from backend.database.repositories.tasks import get_task as db_get_task
from backend.database.repositories.tasks import update_task_status as db_update_task_status
from backend.database.repositories.tasks import upsert_task as db_upsert_task
from backend.lesson_plan_v2.service import generate_lesson_plan_stream
from backend.lesson_plan_v2.store import (
    create_lesson_plan,
    delete_lesson_plan,
    export_lesson_plan_markdown,
    get_lesson_plan,
    list_lesson_plans,
)

router = APIRouter(prefix="/lesson-plans", tags=["lesson-plans"], dependencies=[Depends(require_auth)])
logger = get_logger(__name__)


@router.post("", response_model=LessonPlanResponse)
async def create_plan(
    request: LessonPlanCreateRequest,
    user: dict = Depends(require_auth),
):
    """Create a new lesson plan."""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    plan = create_lesson_plan(
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
    """List all lesson plans."""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    plans = list_lesson_plans(user_id=user_id)
    return LessonPlanListResponse(plans=plans, total=len(plans))


@router.get("/{plan_id}", response_model=LessonPlanResponse)
async def get_plan(plan_id: str):
    """Get a specific lesson plan."""
    plan = get_lesson_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Lesson plan not found")
    return plan


@router.delete("/{plan_id}")
async def delete_plan(plan_id: str, user: dict = Depends(require_auth)):
    """Delete a lesson plan."""
    success = delete_lesson_plan(plan_id)
    if not success:
        raise HTTPException(status_code=404, detail="Lesson plan not found")
    return {"message": "Lesson plan deleted"}


@router.post("/generate")
async def generate_plan(request: LessonPlanGenerateRequest, user: dict = Depends(require_auth)):
    """Generate a lesson plan using AI with streaming response."""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    task_id = f"lesson-plan-{uuid.uuid4().hex[:12]}"
    title = f"教案：{request.subject} {request.grade}《{request.topic}》"
    task_db_ready = False
    try:
        await db_upsert_task(
            user_id=user_id,
            task_id=task_id,
            task_type="lesson_plan",
            title=title[:200],
            status="running",
            progress=0.0,
            request=request.model_dump(),
            started_at=utcnow_naive(),
        )
        await db_append_task_event(
            user_id=user_id,
            task_id=task_id,
            event_type="step",
            payload={
                "step": {
                    "id": "task_started",
                    "title": "开始生成教案",
                    "status": "running",
                    "startTime": utcnow_iso_z(),
                    "toolName": "lesson_plan",
                    "input": {"taskId": task_id},
                }
            },
        )
        task_db_ready = True
    except Exception:
        logger.exception("lesson_plan_task_upsert_failed", extra={"task_id": task_id, "user_id": user_id})

    async def event_generator():
        last_check = 0.0
        async for event in generate_lesson_plan_stream(
            subject=request.subject,
            grade=request.grade,
            topic=request.topic,
            user_id=user_id,
            duration_minutes=request.duration_minutes,
            objectives=request.objectives,
            teaching_style=request.teaching_style,
            student_level=request.student_level,
            additional_requirements=request.additional_requirements,
        ):
            if task_db_ready:
                now = time.monotonic()
                if now - last_check >= 1.0:
                    last_check = now
                    try:
                        current = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
                        if current and str(current.get("status") or "").strip() != "running":
                            break
                    except Exception:
                        logger.debug(
                            "lesson_plan_task_status_check_failed",
                            extra={"task_id": task_id, "user_id": user_id},
                            exc_info=True,
                        )
            try:
                kind = str(event.get("event") or "").strip()
                data = event.get("data") if isinstance(event.get("data"), dict) else {}
                await db_append_task_event(
                    user_id=user_id,
                    task_id=task_id,
                    event_type=kind or "event",
                    payload=data,
                )
                if kind == "done":
                    material = data.get("material") if isinstance(data, dict) else {}
                    await db_update_task_status(
                        user_id=user_id,
                        task_id=task_id,
                        status="completed",
                        progress=100.0,
                        result=material if isinstance(material, dict) else {"material": material},
                        ended_at=utcnow_naive(),
                    )
                elif kind == "error":
                    msg = str((data or {}).get("message") or "lesson_plan_failed")
                    await db_update_task_status(
                        user_id=user_id,
                        task_id=task_id,
                        status="failed",
                        error={"message": msg},
                        ended_at=utcnow_naive(),
                    )
            except Exception:
                logger.exception(
                    "lesson_plan_task_event_write_failed",
                    extra={"task_id": task_id, "user_id": user_id, "event": event},
                )

            event_out = dict(event or {})
            event_out["taskId"] = task_id
            yield f"data: {json.dumps(event_out, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/export", response_model=LessonPlanExportResponse)
async def export_plan(request: LessonPlanExportRequest):
    """Export a lesson plan to various formats."""
    if request.format == "markdown":
        content = export_lesson_plan_markdown(request.plan_id)
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
