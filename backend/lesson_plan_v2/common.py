from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = (REPO_ROOT / ".local" / "media" / "generated").resolve()
GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def lpv2_infinite_max_tokens() -> int:
    raw = (os.getenv("LESSON_PLAN_V2_MAX_TOKENS") or "").strip()
    try:
        v = int(raw) if raw else 0
    except Exception:
        v = 0
    return v if v > 0 else 200000


def agent_event(kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"event": kind, "data": data}


def extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


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
