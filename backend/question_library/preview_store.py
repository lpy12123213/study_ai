from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PREVIEWS_DIR = (_REPO_ROOT / ".local" / "question_library" / "previews").resolve()


def new_preview_id() -> str:
    return f"ql_preview_{uuid.uuid4().hex[:16]}"


def _safe_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    out = []
    for ch in raw:
        if ch.isalnum() or ch in {"_", "-"}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:80]


def _preview_path(preview_id: str) -> Path:
    pid = _safe_id(preview_id)
    if not pid:
        raise ValueError("missing_preview_id")
    return (_PREVIEWS_DIR / f"{pid}.json").resolve()


def save_preview(preview: Dict[str, Any]) -> Dict[str, Any]:
    _PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    obj = dict(preview or {})
    obj.setdefault("created_at_s", time.time())

    path = _preview_path(str(obj.get("preview_id") or "").strip())
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return obj


def load_preview(preview_id: str) -> Optional[dict]:
    try:
        path = _preview_path(preview_id)
    except Exception:
        return None
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        obj = json.loads(raw) if raw else {}
    except Exception:
        obj = {}
    return obj if isinstance(obj, dict) else None


def find_latest_pending_preview(user_id: str) -> Optional[dict]:
    uid = str(user_id or "").strip()
    if not uid:
        return None
    if not _PREVIEWS_DIR.exists():
        return None

    latest_obj: Optional[dict] = None
    latest_score = float("-inf")
    for path in _PREVIEWS_DIR.glob("*.json"):
        try:
            raw = path.read_text(encoding="utf-8")
            obj = json.loads(raw) if raw else {}
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if str(obj.get("user_id") or "").strip() != uid:
            continue
        if str(obj.get("status") or "").strip().lower() != "pending_review":
            continue

        try:
            score = float(obj.get("created_at_s") or 0.0)
        except Exception:
            try:
                score = path.stat().st_mtime
            except Exception:
                score = 0.0
        if latest_obj is None or score > latest_score:
            latest_obj = obj
            latest_score = score

    return latest_obj


def delete_preview(preview_id: str) -> bool:
    try:
        path = _preview_path(preview_id)
    except Exception:
        return False
    try:
        if path.exists():
            path.unlink()
        return True
    except Exception:
        return False
