from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from backend.core.logging_utils import get_request_id, get_trace_id
from backend.core.settings import model_param_int
from backend.llm.json_utils import extract_first_json_object

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = (REPO_ROOT / ".local" / "media" / "generated").resolve()
GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def lesson_plan_infinite_max_tokens() -> int:
    """A very high max_tokens cap for long-form lesson plan generation.

    This is intentionally separate from `LESSON_PLAN_MAX_TOKENS` (which is used
    as the general budget for the app) so long-form writers can opt into a
    higher cap when the provider/model supports it.
    """

    v = model_param_int("lesson_plan_infinite_max_tokens", 0)
    return v if v > 0 else 200000


def agent_event(kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event": kind, "data": data}
    trace_id = get_trace_id() or get_request_id()
    if trace_id:
        payload["trace_id"] = trace_id
    return payload


def extract_json_obj(text: str) -> Dict[str, Any]:
    return extract_first_json_object(text, default={}) or {}


def clean_points(items: List[Any], *, max_points: int) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for it in items or []:
        s = str(it or "").strip()
        s = re.sub(r"\s+", " ", s)
        s = s.strip(" -—·•\t\r\n")
        if not s:
            continue
        if len(s) > 60:
            s = s[:60].rstrip() + "…"
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= max_points:
            break
    return out
