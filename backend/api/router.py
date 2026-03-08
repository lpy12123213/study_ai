from __future__ import annotations

from fastapi import APIRouter

from backend.api.annotations import router as annotations_router
from backend.api.auth import router as auth_router
from backend.api.blueprints import router as blueprints_router
from backend.api.canvas import router as canvas_router
from backend.api.chat import router as chat_router
from backend.api.conversations import router as conversations_router
from backend.api.crawler_tools import router as crawler_tools_router
from backend.api.dashboard import router as dashboard_router
from backend.api.deepthink import router as deepthink_router
from backend.api.exports import router as exports_router
from backend.api.feedback import router as feedback_router
from backend.api.item_meta import router as item_meta_router
from backend.api.learning_plans import router as learning_plans_router
from backend.api.lesson_plan import router as lesson_plan_router
from backend.api.media import router as media_router
from backend.api.models import router as models_router
from backend.api.papers import router as papers_router
from backend.api.question_evaluate import router as question_evaluate_router
from backend.api.question_library import router as question_library_router
from backend.api.share_links import share_links_router, share_public_router
from backend.api.study_archives import router as study_archives_router
from backend.api.study_materials import router as study_materials_router
from backend.api.subjects import router as subjects_router
from backend.api.system import router as system_router
from backend.api.tasks import router as tasks_router
from backend.api.templates import router as templates_router
from backend.api.wrongbook import router as wrongbook_router

api_router = APIRouter(prefix="/api")
api_router.include_router(system_router)
api_router.include_router(models_router)
api_router.include_router(crawler_tools_router)
api_router.include_router(canvas_router)
api_router.include_router(media_router)
api_router.include_router(papers_router)
api_router.include_router(subjects_router)
api_router.include_router(conversations_router)
api_router.include_router(chat_router)
api_router.include_router(auth_router)
api_router.include_router(deepthink_router)
api_router.include_router(lesson_plan_router)
api_router.include_router(study_materials_router)
api_router.include_router(question_evaluate_router)
api_router.include_router(blueprints_router)
api_router.include_router(question_library_router)
api_router.include_router(tasks_router)
api_router.include_router(item_meta_router)
api_router.include_router(study_archives_router)
api_router.include_router(share_links_router)
api_router.include_router(share_public_router)
api_router.include_router(templates_router)
api_router.include_router(annotations_router)
api_router.include_router(feedback_router)
api_router.include_router(wrongbook_router)
api_router.include_router(learning_plans_router)
api_router.include_router(exports_router)
api_router.include_router(dashboard_router)
