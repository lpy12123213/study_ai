from __future__ import annotations

import threading
import time
from typing import Any, Dict, Tuple

from backend.core.settings import LLM_CIRCUIT_BREAKER_FAIL_THRESHOLD, LLM_CIRCUIT_BREAKER_OPEN_SECONDS

_circuit_lock = threading.Lock()
_circuit_state: Dict[str, Dict[str, Any]] = {}


def circuit_key(*, provider: str, model: str) -> str:
    return f"{str(provider or '').strip().lower()}::{str(model or '').strip().lower()}"


def circuit_is_open(key: str) -> Tuple[bool, float]:
    now = time.time()
    with _circuit_lock:
        state = _circuit_state.get(key) or {}
        try:
            open_until = float(state.get("open_until_s") or 0.0)
        except (TypeError, ValueError):
            open_until = 0.0
        if open_until > now:
            return True, max(0.0, open_until - now)
        if open_until:
            state["open_until_s"] = 0.0
            _circuit_state[key] = state
    return False, 0.0


def circuit_record_success(key: str) -> None:
    with _circuit_lock:
        _circuit_state[key] = {"fail_count": 0, "open_until_s": 0.0}


def circuit_record_failure(key: str) -> None:
    try:
        threshold = max(1, int(LLM_CIRCUIT_BREAKER_FAIL_THRESHOLD or 6))
    except (TypeError, ValueError):
        threshold = 6
    try:
        open_s = max(1, int(LLM_CIRCUIT_BREAKER_OPEN_SECONDS or 30))
    except (TypeError, ValueError):
        open_s = 30
    with _circuit_lock:
        state = _circuit_state.get(key) or {"fail_count": 0, "open_until_s": 0.0}
        state["fail_count"] = int(state.get("fail_count") or 0) + 1
        if int(state["fail_count"]) >= threshold:
            state["open_until_s"] = time.time() + float(open_s)
        _circuit_state[key] = state
