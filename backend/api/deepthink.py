from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.schemas import DeepThinkRequest
from backend.core.logging_utils import get_logger
from backend.core.time_utils import utcnow_iso_z, utcnow_naive
from backend.database.repositories.tasks import append_task_event as db_append_task_event
from backend.database.repositories.tasks import get_task as db_get_task
from backend.database.repositories.tasks import update_task_status as db_update_task_status
from backend.database.repositories.tasks import upsert_task as db_upsert_task
from backend.deepthink.service import deepthink_service

router = APIRouter(dependencies=[Depends(require_auth)])
logger = get_logger(__name__)


@router.post("/deepthink")
async def deepthink_endpoint(request: DeepThinkRequest, user: dict = Depends(require_auth)) -> StreamingResponse:
    """
    DeepThink SSE endpoint (POST + streaming response body).
    """

    user_id = str((user or {}).get("user_id") or "").strip()
    task_id = f"deepthink-{uuid.uuid4().hex[:12]}"
    title = f"深度解题：{(request.subject or '高中数学').strip()}"
    task_db_ready = False

    try:
        await db_upsert_task(
            user_id=user_id,
            task_id=task_id,
            task_type="deepthink",
            title=title[:200],
            status="running",
            progress=0.0,
            request=request.model_dump(),
            started_at=utcnow_naive(),
        )
        await db_append_task_event(
            user_id=user_id,
            task_id=task_id,
            event_type="step",
            payload={
                "step": {
                    "id": "task_started",
                    "title": "开始深度解题",
                    "status": "running",
                    "startTime": utcnow_iso_z(),
                    "toolName": "deepthink",
                    "input": {"taskId": task_id},
                }
            },
        )
        task_db_ready = True
    except Exception:
        logger.exception("deepthink_task_upsert_failed", extra={"task_id": task_id, "user_id": user_id})

    async def generate():
        last_check = 0.0
        async for event in deepthink_service.solve(
            question=request.question,
            subject=request.subject or "高中数学",
            image_url=request.image_url,
        ):
            if task_db_ready:
                now = time.monotonic()
                if now - last_check >= 1.0:
                    last_check = now
                    try:
                        current = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
                        if current and str(current.get("status") or "").strip() != "running":
                            break
                    except Exception:
                        logger.debug(
                            "deepthink_task_status_check_failed",
                            extra={"task_id": task_id, "user_id": user_id},
                            exc_info=True,
                        )
            try:
                kind = str(event.get("type") or "event")
                await db_append_task_event(user_id=user_id, task_id=task_id, event_type=kind, payload=dict(event or {}))
                if kind == "done":
                    await db_update_task_status(
                        user_id=user_id,
                        task_id=task_id,
                        status="completed",
                        progress=100.0,
                        result=dict(event or {}),
                        ended_at=utcnow_naive(),
                    )
                elif kind == "error":
                    msg = str(event.get("message") or "deepthink_failed")
                    await db_update_task_status(
                        user_id=user_id,
                        task_id=task_id,
                        status="failed",
                        error={"message": msg},
                        ended_at=utcnow_naive(),
                    )
            except Exception:
                logger.exception(
                    "deepthink_task_event_write_failed", extra={"task_id": task_id, "user_id": user_id, "event": event}
                )

            event_out = dict(event or {})
            event_out["taskId"] = task_id
            yield f"data: {json.dumps(event_out, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
