"""Study materials streaming API endpoints."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.agent.core import AgentCore
from backend.api.auth import get_current_user
from backend.api.study_materials_schemas import StudyMaterialsGenerateRequest


router = APIRouter(prefix="/study-materials", tags=["study-materials"])

_agent = AgentCore()


@router.post("/generate")
async def generate_study_materials(
    request: StudyMaterialsGenerateRequest,
    user: Optional[dict] = Depends(get_current_user),
):
    """Generate study materials using Plan-Act-Reflect with streaming SSE."""

    user_id = (user.get("user_id") if user else None) or "anonymous"

    async def event_generator():
        async for event in _agent.run(request.query, user_id=user_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

