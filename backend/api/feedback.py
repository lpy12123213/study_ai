from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.database.repositories.system.feedback import create_feedback as db_create_feedback
from backend.database.repositories.system.feedback import list_feedback as db_list_feedback

router = APIRouter(prefix="/feedback", tags=["feedback"], dependencies=[Depends(require_auth)])
logger = get_logger(__name__)


async def _try_send_webhook(payload: dict) -> None:
    url = str(os.getenv("FEEDBACK_WEBHOOK_URL") or "").strip()
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            await client.post(url, json=payload)
    except Exception:
        logger.exception("feedback_webhook_send_failed")


@router.get("", response_model=dict)
async def list_user_feedback(
    limit: int = Query(50, ge=1, le=100),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    items = await db_list_feedback(user_id=user_id, limit=limit)
    return {"feedback": items, "count": len(items)}


@router.post("", response_model=dict)
async def create_user_feedback(payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    title = str(payload.get("title") or "反馈").strip()
    description = str(payload.get("description") or "").strip()
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}

    try:
        out = await db_create_feedback(user_id=user_id, title=title, description=description, context=dict(context))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("create_feedback_failed", extra={"user_id": user_id})
        raise HTTPException(status_code=500, detail="create_feedback_failed")

    asyncio.create_task(_try_send_webhook({"feedback": out}))
    return {"success": True, "feedback": out}
