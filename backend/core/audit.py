from __future__ import annotations

import json
import os
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from backend.core.logging_utils import get_client_ip, get_logger, get_request_id

logger = get_logger(__name__)


class AuditAction(str, Enum):
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    USER_REGISTER = "USER_REGISTER"
    DATA_DELETE = "DATA_DELETE"
    API_KEY_USE = "API_KEY_USE"

    PAPER_CREATE = "PAPER_CREATE"
    PAPER_DELETE = "PAPER_DELETE"
    PAPER_EXPORT = "PAPER_EXPORT"

    QUESTION_LIBRARY_COMMIT = "QUESTION_LIBRARY_COMMIT"
    QUESTION_LIBRARY_DISCARD = "QUESTION_LIBRARY_DISCARD"
    QUESTION_LIBRARY_BULK_DELETE = "QUESTION_LIBRARY_BULK_DELETE"


def _truthy(raw: str) -> bool:
    s = (raw or "").strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


def _utc_iso(ts: Optional[float] = None) -> str:
    t = time.gmtime(float(ts) if ts is not None else time.time())
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", t)


class AuditLogger:
    """Append-only JSONL audit trail for sensitive operations.

    Notes:
    - Best-effort: audit logging must never crash the request handler.
    - Never write secrets (API keys, passwords, tokens) into `details`.
    """

    def __init__(self, *, path: Optional[str] = None) -> None:
        # `backend/core/audit.py` -> repo root is 3 levels up.
        repo_root = Path(__file__).resolve().parents[2]
        default_path = repo_root / ".local" / "audit.jsonl"

        configured = str(path or os.getenv("AUDIT_LOG_PATH") or "").strip()
        self._path = Path(configured).expanduser() if configured else default_path
        self._lock = threading.RLock()

    def enabled(self) -> bool:
        raw = os.getenv("AUDIT_LOG_ENABLED")
        if raw is None:
            return True
        return _truthy(raw)

    @property
    def path(self) -> Path:
        return self._path

    def log(
        self,
        *,
        user_id: str,
        action: AuditAction | str,
        resource: str,
        ip: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled():
            return

        uid = str(user_id or "").strip()
        act = str(getattr(action, "value", action) or "").strip() or "UNKNOWN"
        res = str(resource or "").strip()
        if not res:
            res = "unknown_resource"

        ip_str = str(ip or "").strip() or get_client_ip() or ""
        rid = get_request_id() or ""

        payload: Dict[str, Any] = {
            "timestamp": _utc_iso(),
            "user_id": uid,
            "action": act,
            "resource": res,
            "ip": ip_str,
            "details": dict(details or {}),
        }
        if rid:
            payload["request_id"] = rid

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(payload, ensure_ascii=False, default=str)
            with self._lock:
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            logger.warning("audit_log_write_failed", extra={"path": str(self._path)}, exc_info=True)

    def iter_events(self) -> Iterator[Dict[str, Any]]:
        """Iterate audit events from disk (best-effort)."""
        try:
            if not self._path.exists():
                return iter(())
        except OSError:
            return iter(())

        def _gen() -> Iterator[Dict[str, Any]]:
            try:
                with self._path.open("r", encoding="utf-8") as f:
                    for line in f:
                        s = (line or "").strip()
                        if not s:
                            continue
                        try:
                            obj = json.loads(s)
                        except (TypeError, ValueError, json.JSONDecodeError):
                            continue
                        if isinstance(obj, dict):
                            yield obj
            except OSError:
                return

        return _gen()


# Global singleton used across the backend.
audit_logger = AuditLogger()
