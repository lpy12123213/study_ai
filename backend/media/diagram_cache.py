"""Spec-hash based cache for diagram rendering.

Saves a ~30-50% rendering load (TikZ/xelatex is the slow path) by short-circuiting
re-render when the same canonical spec was already rendered. Backed by a single JSON
file under `.local/media/diagram_cache.json`. Best-effort: a missing/corrupt file
just degrades to cold render — never raises.

Cache schema:
{
  "<spec_hash>": {
    "filename": "<sha256>.svg",
    "url": "/api/media/generated/<sha256>.svg",
    "mime_type": "image/svg+xml",
    "bytes": 12345,
    "created_at": "2026-05-23T12:00:00Z",
    "kind": "tikz" | "matplotlib_2d" | ...
  }
}
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from backend.core.logging_utils import get_logger
from backend.core.time_utils import utcnow_naive

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = (_REPO_ROOT / ".local" / "media").resolve()
_CACHE_PATH = _CACHE_DIR / "diagram_cache.json"
_LOCK = asyncio.Lock()


def canonical_spec_hash(kind: str, payload: Any) -> str:
    """Hash a (kind, payload) pair canonically so equivalent specs collide.

    `kind` distinguishes e.g. `tikz` from `matplotlib_2d` so identical TikZ code
    and identical matplotlib spec don't collide.
    """

    try:
        canon = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        canon = repr(payload)
    h = hashlib.sha256()
    h.update((str(kind or "").strip().lower() + "\0").encode("utf-8"))
    h.update(canon.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def _read_cache_sync() -> Dict[str, Dict[str, Any]]:
    try:
        if not _CACHE_PATH.exists():
            return {}
        raw = _CACHE_PATH.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        logger.debug("diagram_cache_read_failed", exc_info=True)
        return {}


def _write_cache_sync(data: Dict[str, Dict[str, Any]]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.debug("diagram_cache_write_failed", exc_info=True)


def _file_for(filename: str) -> Path:
    return (_CACHE_DIR / "generated" / filename).resolve()


async def lookup(spec_hash: str) -> Optional[Dict[str, Any]]:
    """Return cached entry if both JSON record and underlying file exist; else None."""

    if not spec_hash:
        return None
    async with _LOCK:
        data = await asyncio.to_thread(_read_cache_sync)
        entry = data.get(spec_hash)
        if not isinstance(entry, dict):
            return None
        filename = str(entry.get("filename") or "").strip()
        if not filename:
            return None
        # Verify the on-disk file is still there; otherwise drop the entry.
        if not _file_for(filename).exists():
            data.pop(spec_hash, None)
            await asyncio.to_thread(_write_cache_sync, data)
            return None
        return dict(entry)


async def record(
    spec_hash: str,
    *,
    filename: str,
    url: str,
    kind: str = "",
    mime_type: str = "",
    bytes_size: int = 0,
) -> None:
    if not spec_hash or not filename:
        return
    async with _LOCK:
        data = await asyncio.to_thread(_read_cache_sync)
        data[spec_hash] = {
            "filename": filename,
            "url": url,
            "mime_type": mime_type,
            "bytes": int(bytes_size or 0),
            "kind": str(kind or "").strip(),
            "created_at": utcnow_naive().isoformat() + "Z",
        }
        # Bound the cache to avoid unbounded growth; keep newest 5000 entries.
        max_entries = max(100, int(os.getenv("DIAGRAM_CACHE_MAX_ENTRIES") or 5000))
        if len(data) > max_entries:
            keep = sorted(data.items(), key=lambda kv: kv[1].get("created_at") or "", reverse=True)[:max_entries]
            data = dict(keep)
        await asyncio.to_thread(_write_cache_sync, data)


async def invalidate(spec_hash: str) -> None:
    if not spec_hash:
        return
    async with _LOCK:
        data = await asyncio.to_thread(_read_cache_sync)
        if data.pop(spec_hash, None) is not None:
            await asyncio.to_thread(_write_cache_sync, data)
