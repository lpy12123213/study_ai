from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.schemas import DeepThinkRequest
from backend.shared.tasks import task_runtime
from backend.tasks import submit_deepthink_task

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/deepthink")
async def deepthink_endpoint(request: DeepThinkRequest, user: dict = Depends(require_auth)) -> StreamingResponse:
    """
    DeepThink SSE endpoint (POST + streaming response body).

    NOTE:
    - `/api/tasks` is the canonical long-task API.
    - This endpoint is kept as a thin compatibility wrapper for older clients.
    """

    user_id = str((user or {}).get("user_id") or "").strip()
    task = await submit_deepthink_task(user_id=user_id, request=request.model_dump())

    async def generate():
        async for event in task_runtime.stream(task.task_id, after_seq=0):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
