"""Lesson plan persistence (async, DB-backed).

Earlier revisions kept plans in a module-level dict + JSON snapshot. That setup
broke under multi-worker uvicorn deployments and lost data on restart. The
canonical store is now SQL via
:mod:`backend.database.repositories.generation.lesson_plans`; the helpers here
preserve the previous public surface (and Pydantic return types) so callers
don't need to know which backend is in use.

All read/write helpers require ``user_id`` and return ``None`` / ``False`` when
the plan does not exist OR is not owned by the requested user. Cross-tenant
access is rejected before any data is touched.
"""

from __future__ import annotations

from typing import List, Optional

from backend.api.lesson_plan_schemas import (
    LessonPlanObjective,
    LessonPlanResponse,
    LessonPlanSection,
)
from backend.database.repositories.generation import lesson_plans as _repo


def _to_response(plan: Optional[dict]) -> Optional[LessonPlanResponse]:
    if not plan:
        return None
    return LessonPlanResponse(**plan)


async def create_lesson_plan(
    title: str,
    subject: str,
    topic: str,
    grade: Optional[str] = None,
    duration_minutes: int = 45,
    objectives: Optional[List[str]] = None,
    user_id: Optional[str] = None,
) -> LessonPlanResponse:
    """Create a new lesson plan owned by ``user_id``."""

    plan = await _repo.create_lesson_plan(
        user_id=str(user_id or ""),
        title=title,
        subject=subject,
        topic=topic,
        grade=grade,
        duration_minutes=duration_minutes,
        objectives=objectives,
    )
    return LessonPlanResponse(**plan)


async def get_lesson_plan(plan_id: str, user_id: str) -> Optional[LessonPlanResponse]:
    """Fetch a plan by id, scoped to its owner."""

    plan = await _repo.get_lesson_plan(plan_id=plan_id, user_id=user_id)
    return _to_response(plan)


async def list_lesson_plans(user_id: str) -> List[LessonPlanResponse]:
    """List plans owned by ``user_id``."""

    plans = await _repo.list_lesson_plans(user_id=user_id)
    return [LessonPlanResponse(**p) for p in plans]


async def update_lesson_plan(
    plan_id: str,
    user_id: str,
    title: Optional[str] = None,
    objectives: Optional[List[LessonPlanObjective]] = None,
    sections: Optional[List[LessonPlanSection]] = None,
    status: Optional[str] = None,
) -> Optional[LessonPlanResponse]:
    """Patch a plan; returns ``None`` if missing or not owned."""

    objectives_payload = (
        [obj.model_dump() for obj in objectives] if objectives is not None else None
    )
    sections_payload = (
        [sec.model_dump() for sec in sections] if sections is not None else None
    )
    plan = await _repo.update_lesson_plan(
        plan_id=plan_id,
        user_id=user_id,
        title=title,
        objectives=objectives_payload,
        sections=sections_payload,
        status=status,
    )
    return _to_response(plan)


async def delete_lesson_plan(plan_id: str, user_id: str) -> bool:
    return await _repo.delete_lesson_plan(plan_id=plan_id, user_id=user_id)


async def export_lesson_plan_markdown(plan_id: str, user_id: str) -> Optional[str]:
    """Render a plan as Markdown, owner-scoped."""

    plan = await _repo.get_lesson_plan(plan_id=plan_id, user_id=user_id)
    if not plan:
        return None

    lines = [
        f"# {plan.get('title') or ''}",
        "",
        f"**Subject:** {plan.get('subject') or ''}",
        f"**Grade:** {plan.get('grade') or 'N/A'}",
        f"**Topic:** {plan.get('topic') or ''}",
        f"**Duration:** {int(plan.get('duration_minutes') or 0)} minutes",
        "",
        "## Learning Objectives",
        "",
    ]

    for obj in plan.get("objectives") or []:
        if isinstance(obj, dict):
            lines.append(f"- {str(obj.get('description') or '').strip()}")
        else:
            lines.append(f"- {str(obj or '').strip()}")

    lines.append("")
    lines.append("## Lesson Sections")
    lines.append("")

    for section in plan.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "Untitled")
        duration = int(section.get("duration_minutes") or 0)
        lines.append(f"### {title} ({duration} min)")
        lines.append("")
        lines.append(str(section.get("content") or ""))
        lines.append("")

        activities = section.get("activities") or []
        if isinstance(activities, list) and activities:
            lines.append("**Activities:**")
            for act in activities:
                lines.append(f"- {act}")
            lines.append("")

    return "\n".join(lines)


__all__ = [
    "create_lesson_plan",
    "delete_lesson_plan",
    "export_lesson_plan_markdown",
    "get_lesson_plan",
    "list_lesson_plans",
    "update_lesson_plan",
]
