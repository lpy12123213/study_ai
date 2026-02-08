"""Lesson plan API endpoints."""

from __future__ import annotations

import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse

from backend.api.auth import get_current_user
from backend.api.lesson_plan_schemas import (
    LessonPlanCreateRequest,
    LessonPlanResponse,
    LessonPlanListResponse,
    LessonPlanGenerateRequest,
    LessonPlanExportRequest,
    LessonPlanExportResponse,
)
from backend.lesson_plan_service import (
    create_lesson_plan,
    get_lesson_plan,
    list_lesson_plans,
    delete_lesson_plan,
    export_lesson_plan_markdown,
)
from backend.lesson_plan_agent_v2 import generate_lesson_plan_stream

router = APIRouter(prefix="/lesson-plans", tags=["lesson-plans"])


@router.post("", response_model=LessonPlanResponse)
async def create_plan(
    request: LessonPlanCreateRequest,
    user: Optional[dict] = Depends(get_current_user),
):
    """Create a new lesson plan."""
    user_id = user.get("user_id") if user else None
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
async def list_plans(user: Optional[dict] = Depends(get_current_user)):
    """List all lesson plans."""
    user_id = user.get("user_id") if user else None
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
async def delete_plan(plan_id: str, user: Optional[dict] = Depends(get_current_user)):
    """Delete a lesson plan."""
    success = delete_lesson_plan(plan_id)
    if not success:
        raise HTTPException(status_code=404, detail="Lesson plan not found")
    return {"message": "Lesson plan deleted"}


@router.post("/generate")
async def generate_plan(request: LessonPlanGenerateRequest):
    """Generate a lesson plan using AI with streaming response."""
    
    async def event_generator():
        async for event in generate_lesson_plan_stream(
            subject=request.subject,
            grade=request.grade,
            topic=request.topic,
            duration_minutes=request.duration_minutes,
            objectives=request.objectives,
            teaching_style=request.teaching_style,
            student_level=request.student_level,
            additional_requirements=request.additional_requirements,
        ):
            yield f"data: {json.dumps(event)}\n\n"
    
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
