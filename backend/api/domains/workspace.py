from __future__ import annotations

from fastapi import APIRouter

from backend.api.annotations import router as annotations_router
from backend.api.canvas import router as canvas_router
from backend.api.chat import router as chat_router
from backend.api.conversations import router as conversations_router
from backend.api.feedback import router as feedback_router
from backend.api.item_meta import router as item_meta_router
from backend.api.media import router as media_router
from backend.api.papers import router as papers_router
from backend.api.share_links import share_links_router, share_public_router
from backend.api.study_archives import router as study_archives_router
from backend.api.templates import router as templates_router
from backend.api.wrongbook import router as wrongbook_router

router = APIRouter()

# User workspace and content organization (canvas/media/papers/conversations/etc).
router.include_router(canvas_router)
router.include_router(media_router)
router.include_router(papers_router)
router.include_router(conversations_router)
router.include_router(chat_router)
router.include_router(item_meta_router)
router.include_router(study_archives_router)
router.include_router(share_links_router)
router.include_router(share_public_router)
router.include_router(templates_router)
router.include_router(annotations_router)
router.include_router(feedback_router)
router.include_router(wrongbook_router)

