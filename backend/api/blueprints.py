from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import require_auth
from backend.api.blueprint_schemas import BlueprintCreateRequest
from backend.database.repositories.question.blueprints import delete_blueprint, get_blueprint, list_blueprints, save_blueprint

router = APIRouter(prefix="/blueprints", tags=["blueprints"], dependencies=[Depends(require_auth)])


@router.get("/", response_model=List[dict])
async def get_blueprints(user: dict = Depends(require_auth)) -> List[dict]:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return await list_blueprints(user_id=user_id)


@router.get("/{blueprint_id}", response_model=dict)
async def get_one_blueprint(blueprint_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    bp = await get_blueprint(user_id=user_id, blueprint_id=blueprint_id)
    if not bp:
        raise HTTPException(status_code=404, detail="blueprint_not_found")
    return bp


@router.post("/", response_model=dict)
async def create_blueprint(payload: BlueprintCreateRequest, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    if not payload.slots:
        raise HTTPException(status_code=400, detail="missing_slots")
    bp = await save_blueprint(
        user_id=user_id,
        blueprint_id="",
        name=payload.name,
        subject=payload.subject,
        topic=payload.topic or "",
        slots=payload.slots,
    )
    return bp


@router.delete("/{blueprint_id}", response_model=dict)
async def remove_blueprint(blueprint_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await delete_blueprint(user_id=user_id, blueprint_id=blueprint_id)
    if not ok:
        raise HTTPException(status_code=404, detail="blueprint_not_found")
    return {"success": True}
