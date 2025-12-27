from __future__ import annotations

from fastapi import APIRouter

from backend.api.chat import router as chat_router
from backend.api.conversations import router as conversations_router
from backend.api.papers import router as papers_router
from backend.api.subjects import router as subjects_router

api_router = APIRouter(prefix="/api")
api_router.include_router(papers_router)
api_router.include_router(subjects_router)
api_router.include_router(conversations_router)
api_router.include_router(chat_router)

