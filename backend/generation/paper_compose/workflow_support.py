
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from backend.database.repositories.question.question_cache import list_used_question_ids


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _difficulty_from_slot(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw in {"easy", "简单", "容易"}:
        return "简单"
    if raw in {"hard", "困难", "较难"}:
        return "困难"
    if raw in {"medium", "mid", "中等", "适中"}:
        return "中等"
    return (value or "").strip() or "中等"


def _stem_fingerprint(stem: str) -> str:
    s = unicodedata.normalize("NFKC", (stem or "").strip().lower())
    if not s:
        return ""
    s = re.sub(r"\d+(?:\.\d+)?", "0", s)
    s = re.sub(r"[\W_]+", "", s, flags=re.UNICODE)
    s = s[:1500]
    return hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()


def _split_kps(value: Any) -> List[str]:
    if isinstance(value, list):
        out: List[str] = []
        for x in value:
            s = str(x or "").strip()
            if s:
                out.append(s)
        return out
    s = str(value or "").strip()
    if not s:
        return []
    parts = re.split(r"[,，;；、。\\n\\r\\t/|]+", s)
    return [p.strip() for p in parts if p.strip()]


def _kp_match_ratio(required: Sequence[str], candidate: Sequence[str]) -> float:
    required_items = [str(x or "").strip() for x in (required or []) if str(x or "").strip()]
    if not required_items:
        return 0.0
    candidate_items = [str(x or "").strip() for x in (candidate or []) if str(x or "").strip()]
    if not candidate_items:
        return 0.0
    hit = 0
    for r in required_items:
        if any((r in c) or (c in r) for c in candidate_items):
            hit += 1
    return float(hit) / float(max(1, len(required_items)))


def _as_list(v: Any) -> List[Any]:
    if isinstance(v, list):
        return v
    return []


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    raw = str(v or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _clip(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def _format_kps_for_badge(kps: Any) -> str:
    if isinstance(kps, str):
        return _clip(kps, 200)
    if isinstance(kps, list):
        items = [str(x).strip() for x in kps if str(x or "").strip()]
        if not items:
            return ""
        return _clip("、".join(items[:3]), 200)
    return ""


def _normalize_question_type(name: str, available: Sequence[Dict[str, Any]]) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    avail_names = [str(it.get("name") or "").strip() for it in available if isinstance(it, dict)]
    avail_names = [n for n in avail_names if n]
    if raw in avail_names:
        return raw

    aliases = {
        "单选题": ["单选题", "选择题", "单项选择题"],
        "多选题": ["多选题", "选择题", "多项选择题"],
        "填空题": ["填空题"],
        "简答题": ["简答题", "解答题"],
        "计算题": ["计算题", "解答题"],
        "论述题": ["论述题", "解答题"],
    }
    candidates = aliases.get(raw, [raw])
    for cand in candidates:
        if cand in avail_names:
            return cand
    for cand in candidates:
        for n in avail_names:
            if cand and (cand in n or n in cand):
                return n
    return ""


async def _load_used_question_ids(*, user_id: str, subject: str, limit: int = 20000) -> set[str]:
    ids = await list_used_question_ids(limit=limit, subject=str(subject or "").strip() or None, user_id=user_id)
    return {str(x).strip() for x in (ids or []) if str(x or "").strip()}


@dataclass
class _Slot:
    index: int
    question_type_raw: str
    question_type: str
    count: int
    difficulty: str
    keyword: str
