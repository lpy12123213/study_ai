from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ARCHIVE_DIR = (_REPO_ROOT / ".local" / "study_archives").resolve()
_LEGACY_BACKEND_ARCHIVE_DIR = (_REPO_ROOT / "backend" / "study_archives").resolve()
_WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1F]+')
_NON_FILENAME = re.compile(r"[^\w\s.-]+", re.UNICODE)


def default_study_archives_dir() -> Path:
    raw = str(os.getenv("STUDY_ARCHIVES_DIR") or "").strip()
    if not raw:
        return _DEFAULT_ARCHIVE_DIR
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path.resolve()


def resolve_study_archives_dir(value: str = "") -> Path:
    raw = str(value or "").strip()
    if not raw or raw == "study_archives":
        return default_study_archives_dir()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path.resolve()


def safe_study_archive_filename(topic: str, *, now: datetime | None = None) -> str:
    value = unicodedata.normalize("NFKC", str(topic or "")).strip()
    value = _WINDOWS_FORBIDDEN.sub(" ", value)
    value = _NON_FILENAME.sub(" ", value)
    value = re.sub(r"\s+", "-", value).strip("-._ ")
    value = re.sub(r"-{2,}", "-", value)
    value = value[:80].strip("-._ ") if len(value) > 80 else value
    if not value or set(value) <= {"_"}:
        value = "study-archive"

    digest = hashlib.sha1(str(topic or "").encode("utf-8", errors="ignore")).hexdigest()[:8]
    ts = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{value}-{digest}-{ts}.md"


def warn_if_legacy_backend_study_archives_present() -> bool:
    try:
        if not _LEGACY_BACKEND_ARCHIVE_DIR.exists() or not _LEGACY_BACKEND_ARCHIVE_DIR.is_dir():
            return False
        samples = [p.name for p in _LEGACY_BACKEND_ARCHIVE_DIR.iterdir() if p.is_file()]
    except OSError:
        logger.warning("study_archives_legacy_dir_check_failed", exc_info=True)
        return False
    if not samples:
        return False
    logger.warning(
        "study_archives_legacy_backend_dir_nonempty",
        extra={
            "legacy_dir": str(_LEGACY_BACKEND_ARCHIVE_DIR),
            "target_dir": str(default_study_archives_dir()),
            "file_count": len(samples),
            "sample_files": samples[:5],
        },
    )
    return True
