from __future__ import annotations

from backend.core.settings import env_int
from backend.generation.study_materials.orchestrator import StudyMaterialsTaskManager

study_material_tasks = StudyMaterialsTaskManager(
    task_ttl_s=env_int("STUDY_MATERIALS_TASK_TTL_S", 60 * 60),
)
