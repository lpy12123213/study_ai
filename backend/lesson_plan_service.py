"""Lesson plan generation service."""

from __future__ import annotations

import json
import threading
from pathlib import Path
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from backend.api.lesson_plan_schemas import (
    LessonPlanResponse,
    LessonPlanObjective,
    LessonPlanSection,
    LessonPlanGenerateRequest,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = PROJECT_ROOT / ".local"
LESSON_PLANS_PATH = LOCAL_DIR / "lesson_plans.json"
_lesson_plans_lock = threading.RLock()


def _load_lesson_plans_from_disk() -> Dict[str, Dict[str, Any]]:
    try:
        if not LESSON_PLANS_PATH.exists():
            return {}
        raw = LESSON_PLANS_PATH.read_text(encoding="utf-8")
        obj = json.loads(raw) if raw.strip() else {}
        if not isinstance(obj, dict):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in obj.items():
            if not isinstance(k, str) or not isinstance(v, dict):
                continue
            out[k] = dict(v)
        return out
    except Exception:
        return {}


def _save_lesson_plans_to_disk(plans: Dict[str, Dict[str, Any]]) -> None:
    try:
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        tmp = LESSON_PLANS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(LESSON_PLANS_PATH)
    except Exception:
        return


def _bootstrap_lesson_plans() -> Dict[str, Dict[str, Any]]:
    plans = _load_lesson_plans_from_disk()
    _save_lesson_plans_to_disk(plans)
    return plans


_lesson_plans: Dict[str, Dict[str, Any]] = _bootstrap_lesson_plans()


def create_lesson_plan(
    title: str,
    subject: str,
    topic: str,
    grade: Optional[str] = None,
    duration_minutes: int = 45,
    objectives: Optional[List[str]] = None,
    user_id: Optional[str] = None,
) -> LessonPlanResponse:
    """Create a new lesson plan."""
    plan_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    plan = {
        "id": plan_id,
        "title": title,
        "subject": subject,
        "grade": grade,
        "topic": topic,
        "objectives": [
            {"description": obj, "type": "knowledge"}
            for obj in (objectives or [])
        ],
        "sections": [],
        "duration_minutes": duration_minutes,
        "status": "draft",
        "user_id": user_id,
        "created_at": now,
        "updated_at": now,
    }
    
    with _lesson_plans_lock:
        _lesson_plans[plan_id] = plan
        _save_lesson_plans_to_disk(_lesson_plans)
        return LessonPlanResponse(**plan)


def get_lesson_plan(plan_id: str) -> Optional[LessonPlanResponse]:
    """Get a lesson plan by ID."""
    with _lesson_plans_lock:
        plan = _lesson_plans.get(plan_id)
        if not plan:
            return None
        return LessonPlanResponse(**plan)


def list_lesson_plans(user_id: Optional[str] = None) -> List[LessonPlanResponse]:
    """List all lesson plans, optionally filtered by user."""
    with _lesson_plans_lock:
        plans: List[LessonPlanResponse] = []
        for plan in _lesson_plans.values():
            if user_id is None or plan.get("user_id") == user_id:
                plans.append(LessonPlanResponse(**plan))
        return sorted(plans, key=lambda p: p.created_at or "", reverse=True)


def update_lesson_plan(
    plan_id: str,
    title: Optional[str] = None,
    objectives: Optional[List[LessonPlanObjective]] = None,
    sections: Optional[List[LessonPlanSection]] = None,
    status: Optional[str] = None,
) -> Optional[LessonPlanResponse]:
    """Update a lesson plan."""
    with _lesson_plans_lock:
        plan = _lesson_plans.get(plan_id)
        if not plan:
            return None
        
        if title is not None:
            plan["title"] = title
        if objectives is not None:
            plan["objectives"] = [obj.model_dump() for obj in objectives]
        if sections is not None:
            plan["sections"] = [sec.model_dump() for sec in sections]
        if status is not None:
            plan["status"] = status
        
        plan["updated_at"] = datetime.utcnow().isoformat()
        _save_lesson_plans_to_disk(_lesson_plans)
        return LessonPlanResponse(**plan)


def delete_lesson_plan(plan_id: str) -> bool:
    """Delete a lesson plan."""
    with _lesson_plans_lock:
        if plan_id in _lesson_plans:
            del _lesson_plans[plan_id]
            _save_lesson_plans_to_disk(_lesson_plans)
            return True
        return False


def export_lesson_plan_markdown(plan_id: str) -> Optional[str]:
    """Export lesson plan as Markdown."""
    with _lesson_plans_lock:
        plan = _lesson_plans.get(plan_id)
        if not plan:
            return None
    
    lines = [
        f"# {plan['title']}",
        "",
        f"**Subject:** {plan['subject']}",
        f"**Grade:** {plan.get('grade', 'N/A')}",
        f"**Topic:** {plan['topic']}",
        f"**Duration:** {plan['duration_minutes']} minutes",
        "",
        "## Learning Objectives",
        "",
    ]
    
    for obj in plan.get("objectives", []):
        lines.append(f"- {obj.get('description', '')}")
    
    lines.append("")
    lines.append("## Lesson Sections")
    lines.append("")
    
    for section in plan.get("sections", []):
        lines.append(f"### {section.get('title', 'Untitled')} ({section.get('duration_minutes', 0)} min)")
        lines.append("")
        lines.append(section.get("content", ""))
        lines.append("")
        
        activities = section.get("activities", [])
        if activities:
            lines.append("**Activities:**")
            for act in activities:
                lines.append(f"- {act}")
            lines.append("")
    
    return "\n".join(lines)
