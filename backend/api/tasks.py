from __future__ import annotations

import asyncio
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.paper_compose.compose_tasks import compose_tasks
from backend.paper_compose.task_manager import PaperComposeTask
from backend.paper_compose.workflow import compose_paper_events


router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(require_auth)])


def _sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


@router.get("/{task_id}", response_model=dict)
async def get_task_status(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "anonymous"
    payload = await compose_tasks.status_payload(task_id=task_id, user_id=user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="task_not_found")
    return payload


@router.post("/{task_id}/pause", response_model=dict)
async def pause_task(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "anonymous"
    ok = await compose_tasks.pause_task(task_id=task_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="task_not_found")
    return {"success": True}


@router.post("/{task_id}/resume", response_model=dict)
async def resume_task(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "anonymous"

    async def runner_factory(task: PaperComposeTask):
        try:
            async for evt in compose_paper_events(task.request, user_id=user_id):
                if task.status != "running":
                    break
                await compose_tasks.append_event(task, evt)
                kind = str(evt.get("type") or "")
                if kind == "result":
                    await compose_tasks.complete_task(task)
                    return
                if kind == "error":
                    await compose_tasks.fail_task(task, str(evt.get("error") or "compose_failed"))
                    return
        except asyncio.CancelledError:
            await compose_tasks.fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            await compose_tasks.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await compose_tasks.fail_task(task, "Task ended unexpectedly")

    ok = await compose_tasks.resume_task(task_id=task_id, user_id=user_id, runner_factory=runner_factory)
    if not ok:
        raise HTTPException(status_code=404, detail="task_not_found")
    return {"success": True}


@router.get("/{task_id}/stream")
async def stream_task(
    task_id: str,
    after_seq: int = Query(0),
) -> StreamingResponse:
    heartbeat_s = float(os.getenv("PAPER_COMPOSE_SSE_HEARTBEAT_S") or "4.0")

    async def event_generator():
        async for event in compose_tasks.stream(task_id, after_seq=after_seq, heartbeat_s=heartbeat_s):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )
