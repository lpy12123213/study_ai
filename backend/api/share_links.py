from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.database.models import create_share_link as db_create_share_link
from backend.database.models import get_paper as db_get_paper
from backend.database.models import get_share_link as db_get_share_link
from backend.database.models import get_template as db_get_template
from backend.database.models import validate_share_link as db_validate_share_link
from backend.database.repositories.study_archives import get_study_archive as db_get_study_archive

logger = get_logger(__name__)

share_links_router = APIRouter(prefix="/share-links", tags=["share-links"], dependencies=[Depends(require_auth)])
share_public_router = APIRouter(prefix="/share", tags=["share"])


def _is_expired(expires_at: str) -> bool:
    raw = str(expires_at or "").strip()
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc) <= datetime.now(timezone.utc)
    except Exception:
        # Malformed timestamps fail closed.
        return True


def _public_meta(link: dict) -> dict:
    return {
        "token": str(link.get("token") or ""),
        "item_type": str(link.get("item_type") or ""),
        "expires_at": str(link.get("expires_at") or ""),
        "created_at": str(link.get("created_at") or ""),
        "has_password": bool(link.get("has_password")),
    }


@share_links_router.post("", response_model=dict)
async def create_share_link(payload: Optional[dict] = None, user: dict = Depends(require_auth)) -> dict:
    body = payload if isinstance(payload, dict) else {}

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    item_type = str(body.get("item_type") or body.get("type") or "").strip()
    item_id = str(body.get("item_id") or body.get("id") or "").strip()
    if not item_type or not item_id:
        raise HTTPException(status_code=400, detail="missing_item_ref")

    expires_in_s = body.get("expires_in_s") if "expires_in_s" in body else body.get("expiresInS")
    try:
        expires_in_s_int = int(expires_in_s) if expires_in_s is not None else None
    except Exception:
        expires_in_s_int = None

    password = str(body.get("password") or "").strip()
    try:
        link = await db_create_share_link(
            user_id=user_id,
            item_type=item_type,
            item_id=item_id,
            expires_in_s=expires_in_s_int,
            password=password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("create_share_link_failed", extra={"user_id": user_id, "item_type": item_type, "item_id": item_id})
        raise HTTPException(status_code=500, detail="share_link_create_failed")

    return {"success": True, **_public_meta(link)}


@share_public_router.get("/{token}", response_model=dict)
async def get_share_link_meta(token: str) -> dict:
    tok = str(token or "").strip()
    if not tok:
        raise HTTPException(status_code=404, detail="share_link_not_found")

    link = await db_get_share_link(token=tok)
    if not link:
        raise HTTPException(status_code=404, detail="share_link_not_found")

    if _is_expired(str(link.get("expires_at") or "")):
        raise HTTPException(status_code=410, detail="share_link_expired")

    return {"success": True, **_public_meta(link)}


@share_public_router.post("/{token}/validate", response_model=dict)
async def validate_share_link(token: str, payload: Optional[dict] = None) -> dict:
    tok = str(token or "").strip()
    if not tok:
        raise HTTPException(status_code=404, detail="share_link_not_found")

    body = payload if isinstance(payload, dict) else {}
    password = str(body.get("password") or "").strip()

    link = await db_validate_share_link(token=tok, password=password)
    if link:
        return {"success": True, **_public_meta(link)}

    meta = await db_get_share_link(token=tok)
    if not meta:
        raise HTTPException(status_code=404, detail="share_link_not_found")
    if _is_expired(str(meta.get("expires_at") or "")):
        raise HTTPException(status_code=410, detail="share_link_expired")
    raise HTTPException(status_code=403, detail="share_link_password_invalid")


@share_public_router.post("/{token}/content", response_model=dict)
async def fetch_shared_content(token: str, payload: Optional[dict] = None) -> dict:
    tok = str(token or "").strip()
    if not tok:
        raise HTTPException(status_code=404, detail="share_link_not_found")

    body = payload if isinstance(payload, dict) else {}
    password = str(body.get("password") or "").strip()

    link = await db_validate_share_link(token=tok, password=password)
    if not link:
        meta = await db_get_share_link(token=tok)
        if not meta:
            raise HTTPException(status_code=404, detail="share_link_not_found")
        if _is_expired(str(meta.get("expires_at") or "")):
            raise HTTPException(status_code=410, detail="share_link_expired")
        raise HTTPException(status_code=403, detail="share_link_password_invalid")

    owner_user_id = str(link.get("user_id") or "").strip()
    item_type = str(link.get("item_type") or "").strip()
    item_id = str(link.get("item_id") or "").strip()

    if item_type == "paper":
        try:
            pid = int(item_id)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_item_id")
        paper = await db_get_paper(user_id=owner_user_id, paper_id=pid)
        if not paper:
            raise HTTPException(status_code=404, detail="shared_item_not_found")
        return {"success": True, "item_type": "paper", "paper": paper}

    if item_type == "study_archive":
        try:
            aid = int(item_id)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_item_id")
        archive = await db_get_study_archive(user_id=owner_user_id, archive_id=aid)
        if not archive:
            raise HTTPException(status_code=404, detail="shared_item_not_found")
        return {"success": True, "item_type": "study_archive", "study_archive": archive}

    if item_type == "template":
        try:
            tid = int(item_id)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_item_id")
        template = await db_get_template(user_id=owner_user_id, template_id=tid)
        if not template:
            raise HTTPException(status_code=404, detail="shared_item_not_found")
        return {"success": True, "item_type": "template", "template": template}

    raise HTTPException(status_code=400, detail="unsupported_share_item_type")
