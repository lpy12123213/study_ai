from __future__ import annotations

import os

from backend.study_materials.task_manager import StudyMaterialsTaskManager


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


study_material_tasks = StudyMaterialsTaskManager(
    max_tasks=_env_int("STUDY_MATERIALS_MAX_TASKS", 50),
    task_ttl_s=_env_int("STUDY_MATERIALS_TASK_TTL_S", 60 * 60),
    max_events_per_task=_env_int("STUDY_MATERIALS_TASK_MAX_EVENTS", 8000),
)

