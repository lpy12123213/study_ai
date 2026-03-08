"""Lesson plan API schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LessonPlanObjective(BaseModel):
    """Learning objective."""

    description: str
    type: str = "knowledge"  # knowledge, skill, attitude


class LessonPlanSection(BaseModel):
    """A section of the lesson plan."""

    title: str
    duration_minutes: int
    content: str
    activities: List[str] = []
    resources: List[str] = []


class LessonPlanCreateRequest(BaseModel):
    """Request to create a lesson plan."""

    title: str = Field(..., min_length=1, max_length=255)
    subject: str
    grade: Optional[str] = None
    topic: str
    duration_minutes: int = Field(default=45, ge=15, le=180)
    objectives: Optional[List[str]] = None
    additional_requirements: Optional[str] = None


class LessonPlanResponse(BaseModel):
    """Lesson plan response."""

    id: str
    title: str
    subject: str
    grade: Optional[str] = None
    topic: str
    objectives: List[LessonPlanObjective] = []
    sections: List[LessonPlanSection] = []
    duration_minutes: int
    status: str = "draft"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class LessonPlanListResponse(BaseModel):
    """List of lesson plans."""

    plans: List[LessonPlanResponse]
    total: int


class LessonPlanGenerateRequest(BaseModel):
    """Request to generate a lesson plan using AI."""

    subject: str
    grade: str
    topic: str
    duration_minutes: int = 45
    objectives: Optional[List[str]] = None
    teaching_style: Optional[str] = None  # lecture, interactive, project-based
    student_level: Optional[str] = None  # beginner, intermediate, advanced
    additional_requirements: Optional[str] = None


class LessonPlanExportRequest(BaseModel):
    """Request to export a lesson plan."""

    plan_id: str
    format: str = "markdown"  # markdown, docx, pdf


class LessonPlanExportResponse(BaseModel):
    """Export response with download URL or content."""

    content: Optional[str] = None
    download_url: Optional[str] = None
    format: str
    filename: str


class AgentEvent(BaseModel):
    """SSE event from lesson plan agent."""

    event: str  # thinking, tool_call, content, done, error
    data: Dict[str, Any]
