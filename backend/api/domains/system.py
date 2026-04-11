from __future__ import annotations

from fastapi import APIRouter

from backend.api.dashboard import router as dashboard_router
from backend.api.system import router as system_router

router = APIRouter()

# System-level endpoints (health/config/version) and operational dashboards.
router.include_router(system_router)
router.include_router(dashboard_router)

