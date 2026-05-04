from __future__ import annotations

import os
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.database.repositories.system.generated_files import get_generated_file as db_get_generated_file
from backend.database.repositories.system.generated_files import list_generated_files as db_list_generated_files
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes

logger = get_logger(__name__)
router = APIRouter(prefix="/exports", tags=["exports"], dependencies=[Depends(require_auth)])

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GENERATED_DIR = (_REPO_ROOT / ".local" / "media" / "generated").resolve()


def _is_safe_generated_filename(name: str) -> bool:
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        return False
    if len(name) < 8:
        return False
    stem, dot, ext = name.rpartition(".")
    if dot != ".":
        return False
    if len(stem) != 64:
        return False
    if any(c not in "0123456789abcdef" for c in stem.lower()):
        return False
    return ext.lower() in {
        "svg",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "bmp",
        "md",
        "tex",
        "pdf",
        "zip",
        "docx",
        "mp4",
        "srt",
        "json",
        "py",
    }


def _is_expired(expires_at: str) -> bool:
    raw = str(expires_at or "").strip()
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc) <= datetime.now(timezone.utc)
    except ValueError:
        return True


@router.get("/files", response_model=dict)
async def list_files(
    file_type: Optional[str] = Query(None, alias="type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    items = await db_list_generated_files(user_id=user_id, file_type=file_type, limit=limit, offset=offset)
    return {"files": items, "count": len(items)}


@router.post("/zip", response_model=dict)
async def zip_files(payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    filenames = payload.get("filenames")
    if not isinstance(filenames, list):
        raise HTTPException(status_code=400, detail="invalid_filenames")

    cleaned = [str(x or "").strip() for x in filenames if str(x or "").strip()]
    cleaned = [x for x in cleaned if _is_safe_generated_filename(x)]
    cleaned = list(dict.fromkeys(cleaned))  # stable unique
    if not cleaned:
        raise HTTPException(status_code=400, detail="no_files_selected")

    max_files = int(os.getenv("EXPORT_ZIP_MAX_FILES") or "50")
    max_files = max(1, min(max_files, 500))
    cleaned = cleaned[:max_files]

    buf = BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for fn in cleaned:
            meta = await db_get_generated_file(filename=fn)
            if not meta or str(meta.get("user_id") or "").strip() != user_id:
                continue
            if _is_expired(str(meta.get("expires_at") or "")):
                continue
            path = (_GENERATED_DIR / fn).resolve()
            try:
                path.relative_to(_GENERATED_DIR)
            except ValueError:
                continue
            if not path.exists() or not path.is_file():
                continue
            try:
                zf.write(path, arcname=fn)
            except (OSError, RuntimeError, ValueError):
                logger.warning("zip_file_add_failed", extra={"filename": fn}, exc_info=True)
                continue

    data = buf.getvalue()
    if len(data) <= 22:  # empty zip
        raise HTTPException(status_code=400, detail="no_accessible_files")

    out = await publish_generated_bytes(
        data,
        user_id=user_id,
        ext=".zip",
        file_type="zip",
        mime_type="application/zip",
        ttl_s=default_generated_media_ttl_s(),
    )
    return {"success": True, **out}
