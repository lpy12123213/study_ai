from __future__ import annotations

from fastapi import APIRouter

from backend.api.blueprints import router as blueprints_router
from backend.api.deepthink import router as deepthink_router
from backend.api.essay_evaluation import router as essay_evaluation_router
from backend.api.learning_plans import router as learning_plans_router
from backend.api.lesson_plan import router as lesson_plan_router
from backend.api.question_evaluate import router as question_evaluate_router
from backend.api.question_library import router as question_library_router
from backend.api.study_materials import router as study_materials_router

router = APIRouter()

# Content-generation workflows (deepthink/lesson-plan/study-materials/question-library/etc).
router.include_router(deepthink_router)
router.include_router(lesson_plan_router)
router.include_router(study_materials_router)
router.include_router(question_evaluate_router)
router.include_router(blueprints_router)
router.include_router(question_library_router)
router.include_router(learning_plans_router)
router.include_router(essay_evaluation_router)

