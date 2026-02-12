from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.schemas import DeepThinkRequest
from backend.deepthink_service import deepthink_service


router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/deepthink")
async def deepthink_endpoint(request: DeepThinkRequest) -> StreamingResponse:
    """
    DeepThink SSE endpoint (POST + streaming response body).
    """

    async def generate():
        async for event in deepthink_service.solve(
            question=request.question,
            subject=request.subject or "高中数学",
            image_url=request.image_url,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

