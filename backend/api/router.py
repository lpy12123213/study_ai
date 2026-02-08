from __future__ import annotations

from fastapi import APIRouter

from backend.api.chat import router as chat_router
from backend.api.canvas import router as canvas_router
from backend.api.conversations import router as conversations_router
from backend.api.crawler_tools import router as crawler_tools_router
from backend.api.media import router as media_router
from backend.api.models import router as models_router
from backend.api.papers import router as papers_router
from backend.api.subjects import router as subjects_router
from backend.api.system import router as system_router
from backend.api.auth import router as auth_router
from backend.api.lesson_plan import router as lesson_plan_router
from backend.api.study_materials import router as study_materials_router

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
api_router.include_router(lesson_plan_router)
api_router.include_router(study_materials_router)
