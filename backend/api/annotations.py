from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.database.models import create_annotation as db_create_annotation
from backend.database.models import list_annotations as db_list_annotations
from backend.database.models import update_annotation as db_update_annotation

router = APIRouter(prefix="/annotations", tags=["annotations"], dependencies=[Depends(require_auth)])
logger = get_logger(__name__)


@router.get("", response_model=dict)
async def list_user_annotations(
    item_type: Optional[str] = Query(None),
    item_id: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=200),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    items = await db_list_annotations(
        user_id=user_id,
        item_type=item_type,
        item_id=item_id,
        tag=tag,
        limit=limit,
    )
    return {"annotations": items, "count": len(items)}


@router.post("", response_model=dict)
async def create_user_annotation(payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    item_type = str(payload.get("item_type") or "").strip()
    item_id = str(payload.get("item_id") or "").strip()
    anchor = str(payload.get("anchor") or "").strip()
    snippet = str(payload.get("snippet") or "").strip()
    content = str(payload.get("content") or "").strip()
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else None

    try:
        out = await db_create_annotation(
            user_id=user_id,
            item_type=item_type,
            item_id=item_id,
            anchor=anchor,
            snippet=snippet,
            content=content,
            tags=tags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("create_annotation_failed", extra={"user_id": user_id, "item_type": item_type, "item_id": item_id})
        raise HTTPException(status_code=500, detail="create_annotation_failed")

    return {"success": True, "annotation": out}


@router.get("/export", response_model=dict)
async def export_user_annotations(user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    items = await db_list_annotations(user_id=user_id, limit=200)
    return {"annotations": items, "count": len(items)}


@router.patch("/{annotation_id}", response_model=dict)
async def update_user_annotation(annotation_id: int, payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    body = payload if isinstance(payload, dict) else {}
    content = body.get("content") if "content" in body else None
    tags = body.get("tags") if isinstance(body.get("tags"), list) else None
    if "tags" in body and tags is None and body.get("tags") is not None:
        raise HTTPException(status_code=400, detail="invalid_tags")

    try:
        out = await db_update_annotation(user_id=user_id, annotation_id=int(annotation_id or 0), content=content, tags=tags)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("update_annotation_failed", extra={"user_id": user_id, "annotation_id": annotation_id})
        raise HTTPException(status_code=500, detail="update_annotation_failed")

    if not out:
        raise HTTPException(status_code=404, detail="annotation_not_found")

    return {"success": True, "annotation": out}
