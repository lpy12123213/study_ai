from __future__ import annotations

import hashlib
import mimetypes
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.exc import SQLAlchemyError

from backend.core.logging_utils import get_logger
from backend.core.time_utils import utcnow_naive
from backend.database.repositories.system.generated_files import (
    delete_generated_file,
    list_expired_generated_files,
    upsert_generated_file,
)

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GENERATED_DIR = (_REPO_ROOT / ".local" / "media" / "generated").resolve()

_ALLOWED_EXTS = {
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".md",
    ".tex",
    ".pdf",
    ".zip",
    ".docx",
    ".mp4",
    ".srt",
    ".json",
    ".py",
}


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


def _normalize_ext(ext: str) -> str:
    suffix = str(ext or "").strip().lower()
    if not suffix:
        return ""
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return suffix


def _guess_mime_type(filename: str, fallback: str = "") -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return str(guessed or fallback or "").strip()


def _expires_at_from_ttl(ttl_s: Optional[int]) -> Optional[datetime]:
    if ttl_s is None:
        return None
    try:
        ttl = int(ttl_s)
    except (TypeError, ValueError):
        ttl = 0
    if ttl <= 0:
        return None
    return utcnow_naive() + timedelta(seconds=ttl)


def _safe_filename_for_bytes(data: bytes, ext: str, *, user_id: str) -> Tuple[str, str]:
    sha = hashlib.sha256(data).hexdigest()
    scoped = hashlib.sha256(str(user_id or "").strip().encode("utf-8") + b"\0" + data).hexdigest()
    suffix = _normalize_ext(ext)
    if not suffix or suffix not in _ALLOWED_EXTS:
        raise ValueError("unsupported_extension")
    return f"{scoped}{suffix}", sha


async def publish_generated_bytes(
    data: bytes,
    *,
    user_id: str,
    ext: str,
    file_type: str,
    mime_type: str = "",
    ttl_s: Optional[int] = None,
) -> Dict[str, Any]:
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("missing_user_id")

    payload = bytes(data or b"")
    filename, sha = _safe_filename_for_bytes(payload, ext, user_id=uid)

    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = (_GENERATED_DIR / filename).resolve()
    if not out_path.exists():
        out_path.write_bytes(payload)

    expires_at = _expires_at_from_ttl(ttl_s)
    mime = str(mime_type or "").strip() or _guess_mime_type(filename, fallback="application/octet-stream")

    try:
        await upsert_generated_file(
            filename=filename,
            user_id=uid,
            file_type=str(file_type or "").strip(),
            mime_type=mime,
            sha256=sha,
            bytes_size=len(payload),
            expires_at=expires_at,
        )
    except (SQLAlchemyError, ValueError):
        logger.exception("upsert_generated_file_failed", extra={"filename": filename, "user_id": uid})

    url = f"/api/media/generated/{filename}"
    return {"url": url, "filename": filename, "sha256": sha, "bytes": len(payload), "expires_at": expires_at.isoformat() if expires_at else ""}


async def publish_generated_text(
    text: str,
    *,
    user_id: str,
    ext: str,
    file_type: str,
    mime_type: str = "",
    ttl_s: Optional[int] = None,
) -> Dict[str, Any]:
    t = str(text or "")
    if not t.endswith("\n"):
        t += "\n"
    return await publish_generated_bytes(
        t.encode("utf-8", errors="ignore"),
        user_id=user_id,
        ext=ext,
        file_type=file_type,
        mime_type=mime_type or "text/plain; charset=utf-8",
        ttl_s=ttl_s,
    )


def default_generated_media_ttl_s() -> int:
    """Default TTL for generated files served over HTTP."""

    return max(60, min(_env_int("GENERATED_MEDIA_TTL_SECONDS", 7 * 24 * 3600), 365 * 24 * 3600))


async def cleanup_expired_generated_files(*, limit: int = 200) -> Dict[str, Any]:
    """Best-effort cleanup for expired generated files.

    - Deletes files from `.local/media/generated/`.
    - Deletes corresponding DB metadata rows.
    """

    limit = max(1, min(int(limit or 200), 5000))
    expired = await list_expired_generated_files(limit=limit)

    deleted_files = 0
    missing_files = 0
    deleted_rows = 0
    errors: list[str] = []

    for meta in expired:
        filename = str((meta or {}).get("filename") or "").strip()
        if not filename:
            continue

        path = (_GENERATED_DIR / filename).resolve()
        try:
            path.relative_to(_GENERATED_DIR)
        except ValueError:
            # Never delete outside the generated dir.
            continue

        try:
            if path.exists() and path.is_file():
                path.unlink()
                deleted_files += 1
            else:
                missing_files += 1
        except OSError as exc:  # pragma: no cover (best-effort)
            errors.append(f"unlink_failed:{filename}:{exc}")

        try:
            ok = await delete_generated_file(filename=filename)
            if ok:
                deleted_rows += 1
        except (SQLAlchemyError, ValueError) as exc:  # pragma: no cover (best-effort)
            errors.append(f"db_delete_failed:{filename}:{exc}")

    return {
        "success": True,
        "checked": len(expired),
        "deleted_files": deleted_files,
        "missing_files": missing_files,
        "deleted_rows": deleted_rows,
        "errors": errors[:50],
        "now": utcnow_naive().isoformat(),
    }
