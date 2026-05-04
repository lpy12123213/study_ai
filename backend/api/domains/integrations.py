from __future__ import annotations

from fastapi import APIRouter

from backend.api.crawler_tools import router as crawler_tools_router
from backend.api.integrations.openai_adapter import router as openai_adapter_router
from backend.api.subjects import router as subjects_router

router = APIRouter()

# External integrations and IO boundaries (crawler/search providers).
router.include_router(crawler_tools_router)
router.include_router(subjects_router)
router.include_router(openai_adapter_router, prefix="/integrations/openai")
