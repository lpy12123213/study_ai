from __future__ import annotations

import os

from backend.study_materials.orchestrator import StudyMaterialsTaskManager


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


study_material_tasks = StudyMaterialsTaskManager(
    task_ttl_s=_env_int("STUDY_MATERIALS_TASK_TTL_S", 60 * 60),
)
