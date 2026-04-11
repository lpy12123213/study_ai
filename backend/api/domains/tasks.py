from __future__ import annotations

from fastapi import APIRouter

from backend.api.exports import router as exports_router
from backend.api.tasks import router as tasks_router

router = APIRouter()

# Long-running task submission/streaming and export flows.
router.include_router(tasks_router)
router.include_router(exports_router)

