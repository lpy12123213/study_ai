from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PREVIEWS_DIR = (_REPO_ROOT / ".local" / "question_library" / "previews").resolve()
_SESSIONS_DIR = (_REPO_ROOT / ".local" / "question_library" / "sessions").resolve()


def new_preview_id() -> str:
    return f"ql_preview_{uuid.uuid4().hex[:16]}"


def new_session_id() -> str:
    return f"ql_session_{uuid.uuid4().hex[:16]}"


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


def _session_path(session_id: str) -> Path:
    sid = _safe_id(session_id)
    if not sid:
        raise ValueError("missing_session_id")
    return (_SESSIONS_DIR / f"{sid}.json").resolve()


def save_preview(preview: Dict[str, Any]) -> Dict[str, Any]:
    _PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    obj = dict(preview or {})
    obj.setdefault("created_at_s", time.time())
    obj["updated_at_s"] = time.time()

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


def save_session(session: Dict[str, Any]) -> Dict[str, Any]:
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    obj = dict(session or {})
    now_s = time.time()
    obj.setdefault("created_at_s", now_s)
    obj["updated_at_s"] = now_s

    raw_tasks = obj.get("task_ids")
    if isinstance(raw_tasks, list):
        seen_tasks: set[str] = set()
        task_ids: List[str] = []
        for task_id in raw_tasks:
            value = str(task_id or "").strip()
            if not value or value in seen_tasks:
                continue
            seen_tasks.add(value)
            task_ids.append(value)
        obj["task_ids"] = task_ids
        if task_ids:
            obj["latest_task_id"] = task_ids[-1]

    raw_confirmed = obj.get("confirmed_question_ids")
    if isinstance(raw_confirmed, list):
        obj["confirmed_question_ids"] = [str(item or "").strip() for item in raw_confirmed if str(item or "").strip()]

    raw_preview_ids = obj.get("preview_ids")
    if isinstance(raw_preview_ids, list):
        obj["preview_ids"] = [str(item or "").strip() for item in raw_preview_ids if str(item or "").strip()]

    path = _session_path(str(obj.get("session_id") or "").strip())
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return obj


def load_session(session_id: str) -> Optional[dict]:
    try:
        path = _session_path(session_id)
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


def list_sessions(user_id: str, *, include_archived: bool = True, limit: int = 50) -> List[dict]:
    uid = str(user_id or "").strip()
    if not uid or not _SESSIONS_DIR.exists():
        return []

    items: List[dict] = []
    for path in _SESSIONS_DIR.glob("*.json"):
        try:
            raw = path.read_text(encoding="utf-8")
            obj = json.loads(raw) if raw else {}
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if str(obj.get("user_id") or "").strip() != uid:
            continue
        status = str(obj.get("status") or "").strip().lower()
        if (not include_archived) and status.startswith("archived"):
            continue
        items.append(obj)

    def sort_key(item: dict) -> float:
        try:
            return float(item.get("updated_at_s") or item.get("created_at_s") or 0.0)
        except Exception:
            return 0.0

    items.sort(key=sort_key, reverse=True)
    return items[: max(1, int(limit or 50))]


def find_session_by_preview_id(user_id: str, preview_id: str) -> Optional[dict]:
    uid = str(user_id or "").strip()
    pid = str(preview_id or "").strip()
    if not uid or not pid or not _SESSIONS_DIR.exists():
        return None

    for obj in list_sessions(uid, include_archived=True, limit=500):
        if str(obj.get("preview_id") or "").strip() == pid:
            return obj
        preview_ids = obj.get("preview_ids")
        if isinstance(preview_ids, list) and pid in {str(item or "").strip() for item in preview_ids}:
            return obj
    return None


def find_preview_by_session_id(user_id: str, session_id: str) -> Optional[dict]:
    uid = str(user_id or "").strip()
    sid = str(session_id or "").strip()
    if not uid or not sid or not _PREVIEWS_DIR.exists():
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
        if str(obj.get("session_id") or "").strip() != sid:
            continue
        try:
            score = float(obj.get("updated_at_s") or obj.get("created_at_s") or 0.0)
        except Exception:
            score = 0.0
        if latest_obj is None or score > latest_score:
            latest_obj = obj
            latest_score = score
    return latest_obj


def mark_running_sessions_interrupted(*, reason: str = "server_restarted", limit: int = 5000) -> int:
    """Best-effort local recovery: prevent sessions stuck in 'running' after restart.

    Question-library sessions/previews are stored as JSON under `.local/question_library/`.
    If the process restarts mid-run, these JSON blobs can remain at status=running which
    confuses the frontend (it keeps waiting for streaming events).

    This helper downgrades running sessions to `interrupted` so they become reviewable
    or restartable.
    """

    if not _SESSIONS_DIR.exists():
        return 0

    try:
        limit_n = int(limit or 0)
    except Exception:
        limit_n = 5000
    limit_n = max(1, min(limit_n, 50_000))

    changed = 0
    for idx, path in enumerate(_SESSIONS_DIR.glob("*.json")):
        if idx >= limit_n:
            break
        try:
            raw = path.read_text(encoding="utf-8")
            obj = json.loads(raw) if raw else {}
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        status = str(obj.get("status") or "").strip().lower()
        if status != "running":
            continue
        obj = dict(obj)
        obj["status"] = "interrupted"
        obj["stop_requested"] = True
        obj["interrupted_reason"] = str(reason or "server_restarted").strip() or "server_restarted"
        obj["interrupted_at_s"] = time.time()
        try:
            path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
            changed += 1
        except Exception:
            continue
    return changed


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
