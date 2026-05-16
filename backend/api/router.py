from __future__ import annotations

from fastapi import APIRouter

from backend.api.domains.auth import router as auth_domain_router
from backend.api.domains.generation import router as generation_domain_router
from backend.api.domains.integrations import router as integrations_domain_router
from backend.api.domains.system import router as system_domain_router
from backend.api.domains.tasks import router as tasks_domain_router
from backend.api.domains.workspace import router as workspace_domain_router
from backend.api.ws import router as ws_router

api_router = APIRouter(prefix="/api")

# Domain-level aggregation. Individual routers keep their own prefixes/tags.
api_router.include_router(system_domain_router)
api_router.include_router(integrations_domain_router)
api_router.include_router(workspace_domain_router)
api_router.include_router(auth_domain_router)
api_router.include_router(generation_domain_router)
api_router.include_router(tasks_domain_router)
api_router.include_router(ws_router)
