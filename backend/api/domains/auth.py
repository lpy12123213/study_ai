from __future__ import annotations

from fastapi import APIRouter

from backend.api.auth import router as auth_router

router = APIRouter()
router.include_router(auth_router)

