from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _truthy(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def replay_enabled() -> bool:
    mode = str(os.getenv("RECORD_REPLAY_MODE") or "").strip().lower()
    if mode:
        # Explicit mode takes precedence over legacy flags.
        if mode == "replay":
            return True
        if mode == "record":
            return False
        if mode in {"off", "none", "disable", "disabled", "0"}:
            return False
    return _truthy(os.getenv("REPLAY"))


def record_enabled() -> bool:
    mode = str(os.getenv("RECORD_REPLAY_MODE") or "").strip().lower()
    if mode:
        # Explicit mode takes precedence over legacy flags.
        if mode == "record":
            return True
        if mode == "replay":
            return False
        if mode in {"off", "none", "disable", "disabled", "0"}:
            return False
    return _truthy(os.getenv("RECORD"))


def fixtures_root() -> Path:
    # repo root: backend/core/record_replay.py -> backend/core -> backend -> repo
    repo_root = Path(__file__).resolve().parents[2]
    raw = str(os.getenv("RECORD_REPLAY_DIR") or "").strip()
    if raw:
        try:
            return Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            return (repo_root / ".local" / "fixtures").resolve()
    return (repo_root / ".local" / "fixtures").resolve()


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(obj: Any) -> str:
    raw = _stable_json(obj).encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


class RecordReplayStore:
    """A tiny record/replay store for flaky external dependencies.

    - Records fixtures under `.local/fixtures/<namespace>/<sha>.json` by default.
    - Replays by hashing a stable representation of the request.
    """

    def __init__(self, namespace: str, *, root: Optional[Path] = None) -> None:
        ns = str(namespace or "").strip()
        if not ns:
            ns = "default"
        self._namespace = ns
        self._root = root if isinstance(root, Path) else fixtures_root()

    def key_for_request(self, request: Any) -> str:
        return fingerprint({"namespace": self._namespace, "request": request})

    def _path_for_key(self, key: str) -> Path:
        safe = str(key or "").strip()
        if not safe:
            safe = "missing"
        return (self._root / self._namespace / f"{safe}.json").resolve()

    def load(self, *, request: Any) -> Tuple[Optional[Dict[str, Any]], str]:
        key = self.key_for_request(request)
        path = self._path_for_key(key)
        try:
            if not path.exists():
                return None, key
            raw = path.read_text(encoding="utf-8")
            obj = json.loads(raw) if raw.strip() else {}
            if not isinstance(obj, dict):
                return None, key
            return obj, key
        except (OSError, json.JSONDecodeError, TypeError):
            return None, key

    def save(self, *, request: Any, response: Any, meta: Optional[Dict[str, Any]] = None) -> str:
        key = self.key_for_request(request)
        path = self._path_for_key(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "ts_s": time.time(),
                "namespace": self._namespace,
                "request": request,
                "response": response,
                "meta": dict(meta or {}),
            }
            path.write_text(_stable_json(payload), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            return key
        return key
