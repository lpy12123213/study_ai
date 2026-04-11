from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.database.repositories.content.study_archives import (
    get_study_archive,
    list_study_archives,
    upsert_study_archive,
)

router = APIRouter(prefix="/study-archives", tags=["study-archives"], dependencies=[Depends(require_auth)])


@router.get("", response_model=dict)
async def list_archives(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10_000),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    rows = await list_study_archives(user_id=user_id, limit=limit, offset=offset)
    return {"items": rows, "count": len(rows)}


@router.get("/{archive_id}", response_model=dict)
async def get_archive(archive_id: int, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    row = await get_study_archive(user_id=user_id, archive_id=int(archive_id or 0))
    if not row:
        raise HTTPException(status_code=404, detail="archive_not_found")
    return row


@router.post("", response_model=dict)
async def create_archive(payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    body = payload if isinstance(payload, dict) else {}
    subject = str(body.get("subject") or "").strip()
    topic = str(body.get("topic") or "").strip()
    preset = str(body.get("preset") or "").strip()
    requirements = str(body.get("requirements") or "").strip()
    markdown = str(body.get("markdown") or "")
    sections = body.get("sections") if isinstance(body.get("sections"), list) else []

    if not subject or not topic:
        raise HTTPException(status_code=400, detail="missing_subject_or_topic")
    if not markdown.strip():
        raise HTTPException(status_code=400, detail="missing_markdown")

    out = await upsert_study_archive(
        user_id=user_id,
        subject=subject,
        topic=topic,
        preset=preset,
        requirements=requirements,
        markdown=markdown,
        sections=[x for x in sections if isinstance(x, dict)],
    )

    row = await get_study_archive(user_id=user_id, archive_id=int(out.get("id") or 0))
    return {"success": True, "archive": row or out}


@router.post("/{archive_id}/clone", response_model=dict)
async def clone_archive(archive_id: int, payload: Optional[dict] = None, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    src = await get_study_archive(user_id=user_id, archive_id=int(archive_id or 0))
    if not src:
        raise HTTPException(status_code=404, detail="archive_not_found")

    body = payload if isinstance(payload, dict) else {}
    topic = str(body.get("topic") or src.get("topic") or "").strip()
    requirements = str(body.get("requirements") or src.get("requirements") or "").strip()
    preset = str(body.get("preset") or src.get("preset") or "").strip()

    out = await upsert_study_archive(
        user_id=user_id,
        subject=str(src.get("subject") or "").strip(),
        topic=topic,
        preset=preset,
        requirements=requirements,
        markdown=str(src.get("markdown") or ""),
        sections=[x for x in (src.get("sections") or []) if isinstance(x, dict)],
    )

    row = await get_study_archive(user_id=user_id, archive_id=int(out.get("id") or 0))
    return {"success": True, "archive": row or out}
