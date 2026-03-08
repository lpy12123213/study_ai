from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.database.models import create_template as db_create_template
from backend.database.models import delete_template as db_delete_template
from backend.database.models import get_template as db_get_template
from backend.database.models import list_templates as db_list_templates
from backend.database.models import update_template as db_update_template

router = APIRouter(prefix="/templates", tags=["templates"], dependencies=[Depends(require_auth)])
logger = get_logger(__name__)


@router.get("", response_model=dict)
async def list_user_templates(
    template_type: Optional[str] = Query(None, alias="type"),
    limit: int = Query(200, ge=1, le=200),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    items = await db_list_templates(user_id=user_id, template_type=template_type, limit=limit)
    return {"templates": items, "count": len(items)}


@router.post("", response_model=dict)
async def create_user_template(payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    template_type = str(payload.get("template_type") or payload.get("type") or "").strip()
    name = str(payload.get("name") or payload.get("title") or "").strip()
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}

    try:
        out = await db_create_template(user_id=user_id, template_type=template_type, name=name, body=dict(body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("create_template_failed", extra={"user_id": user_id, "template_type": template_type})
        raise HTTPException(status_code=500, detail="create_template_failed")

    return {"success": True, "template": out}


@router.put("/{template_id}", response_model=dict)
async def update_user_template(template_id: int, payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    name = payload.get("name") if "name" in payload else payload.get("title")
    template_type = payload.get("template_type") if "template_type" in payload else payload.get("type")
    body = payload.get("body") if "body" in payload else None
    body_dict = body if isinstance(body, dict) else None

    try:
        out = await db_update_template(
            user_id=user_id,
            template_id=int(template_id),
            name=str(name) if name is not None else None,
            template_type=str(template_type) if template_type is not None else None,
            body=body_dict,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("update_template_failed", extra={"user_id": user_id, "template_id": template_id})
        raise HTTPException(status_code=500, detail="update_template_failed")

    if not out:
        raise HTTPException(status_code=404, detail="template_not_found")
    return {"success": True, "template": out}


@router.delete("/{template_id}", response_model=dict)
async def delete_user_template(template_id: int, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    ok = await db_delete_template(user_id=user_id, template_id=int(template_id))
    if not ok:
        raise HTTPException(status_code=404, detail="template_not_found")
    return {"success": True}


@router.get("/export", response_model=dict)
async def export_user_templates(
    template_type: Optional[str] = Query(None, alias="type"),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    items = await db_list_templates(user_id=user_id, template_type=template_type, limit=200)
    return {"templates": items, "count": len(items)}


@router.post("/import", response_model=dict)
async def import_user_templates(payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    templates = payload.get("templates")
    if not isinstance(templates, list):
        raise HTTPException(status_code=400, detail="invalid_templates")

    created: List[dict] = []
    for raw in templates:
        if not isinstance(raw, dict):
            continue
        ttype = str(raw.get("template_type") or raw.get("type") or "").strip()
        name = str(raw.get("name") or raw.get("title") or "").strip()
        body = raw.get("body") if isinstance(raw.get("body"), dict) else {}
        if not ttype:
            continue
        try:
            created.append(await db_create_template(user_id=user_id, template_type=ttype, name=name, body=dict(body)))
        except Exception:
            logger.debug("import_template_skipped", extra={"user_id": user_id, "template_type": ttype, "name": name}, exc_info=True)
            continue

    return {"success": True, "created": created, "count": len(created)}


@router.get("/{template_id}", response_model=dict)
async def get_user_template(template_id: int, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    tpl = await db_get_template(user_id=user_id, template_id=int(template_id))
    if not tpl:
        raise HTTPException(status_code=404, detail="template_not_found")
    return {"template": tpl}

