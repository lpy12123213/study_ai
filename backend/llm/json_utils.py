from __future__ import annotations

import json
import re
import threading
from typing import Any, Dict, Literal, Optional, TypeVar

JsonParseMode = Literal["strict", "lenient"]
T = TypeVar("T")

_FENCE_PREFIX_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*")
_FENCE_SUFFIX_RE = re.compile(r"\s*```$")
_stats_lock = threading.Lock()
_stats: Dict[str, int] = {}


def _record(kind: str, ok: bool) -> None:
    key = f"{kind}_{'success' if ok else 'failure'}"
    with _stats_lock:
        _stats[key] = int(_stats.get(key, 0)) + 1


def json_parse_stats() -> Dict[str, int]:
    with _stats_lock:
        return dict(_stats)


def reset_json_parse_stats() -> None:
    with _stats_lock:
        _stats.clear()


def strip_code_fences(text: str) -> str:
    raw = (text or "").strip()
    if not raw.startswith("```"):
        return raw
    raw = _FENCE_PREFIX_RE.sub("", raw, count=1).lstrip()
    raw = _FENCE_SUFFIX_RE.sub("", raw, count=1).rstrip()
    return raw.strip()


def _load_json(candidate: str) -> Any:
    return json.loads(candidate.strip())


def _slice_between(raw: str, left_token: str, right_token: str) -> str:
    left = raw.find(left_token)
    right = raw.rfind(right_token)
    if left < 0 or right <= left:
        return ""
    return raw[left : right + 1].strip()


def _candidate_values(raw: str, *, mode: JsonParseMode) -> list[str]:
    cleaned = strip_code_fences(raw)
    candidates = [cleaned] if cleaned else []
    if mode == "lenient":
        obj = _slice_between(cleaned, "{", "}")
        if obj and obj not in candidates:
            candidates.append(obj)
        arr = _slice_between(cleaned, "[", "]")
        if arr and arr not in candidates:
            candidates.append(arr)
    return candidates


def extract_json_value(text: str, *, default: T, mode: JsonParseMode = "lenient") -> Any | T:
    for candidate in _candidate_values(text, mode=mode):
        try:
            value = _load_json(candidate)
            _record("value", True)
            return value
        except json.JSONDecodeError:
            continue
    _record("value", False)
    return default


def extract_first_json_object(
    text: str,
    *,
    default: Optional[Dict[str, Any]] = None,
    mode: JsonParseMode = "lenient",
) -> Optional[Dict[str, Any]]:
    raw = strip_code_fences(text)
    for candidate in _candidate_values(raw, mode=mode):
        try:
            value = _load_json(candidate)
            if isinstance(value, dict):
                _record("object", True)
                return value
        except json.JSONDecodeError:
            continue

    if mode == "lenient" and raw:
        decoder = json.JSONDecoder()
        starts = [i for i, ch in enumerate(raw) if ch == "{"]
        for start in reversed(starts):
            try:
                value, _end = decoder.raw_decode(raw[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                _record("object", True)
                return value

    _record("object", False)
    return default


def extract_first_json_array(
    text: str,
    *,
    default: Optional[list[Any]] = None,
    mode: JsonParseMode = "lenient",
) -> Optional[list[Any]]:
    for candidate in _candidate_values(text, mode=mode):
        try:
            value = _load_json(candidate)
            if isinstance(value, list):
                _record("array", True)
                return value
        except json.JSONDecodeError:
            continue
    _record("array", False)
    return default
