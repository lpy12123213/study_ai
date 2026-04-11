from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.database.repositories.system.item_meta import get_item_meta, list_item_meta, upsert_item_meta

router = APIRouter(prefix="/meta", tags=["meta"], dependencies=[Depends(require_auth)])


@router.get("", response_model=dict)
async def list_meta(
    item_type: Optional[str] = Query(None),
    starred: Optional[bool] = Query(None),
    pinned: Optional[bool] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    rows = await list_item_meta(
        user_id=user_id,
        item_type=item_type,
        starred=starred,
        pinned=pinned,
        tag=tag,
        limit=limit,
    )
    return {"items": rows, "count": len(rows)}


@router.get("/{item_type}/{item_id}", response_model=dict)
async def get_meta(item_type: str, item_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    row = await get_item_meta(user_id=user_id, item_type=item_type, item_id=item_id)
    if row:
        return row
    return {
        "user_id": user_id,
        "item_type": str(item_type or "").strip(),
        "item_id": str(item_id or "").strip(),
        "starred": False,
        "pinned": False,
        "tags": [],
    }


@router.post("/{item_type}/{item_id}", response_model=dict)
async def set_meta(
    item_type: str,
    item_id: str,
    payload: dict,
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    starred = payload.get("starred") if "starred" in payload else None
    pinned = payload.get("pinned") if "pinned" in payload else None
    tags = payload.get("tags") if "tags" in payload else None
    if tags is not None and not isinstance(tags, list):
        raise HTTPException(status_code=400, detail="invalid_tags")

    row = await upsert_item_meta(
        user_id=user_id,
        item_type=item_type,
        item_id=item_id,
        starred=bool(starred) if starred is not None else None,
        pinned=bool(pinned) if pinned is not None else None,
        tags=[str(x).strip() for x in tags] if isinstance(tags, list) else None,
    )
    return row
