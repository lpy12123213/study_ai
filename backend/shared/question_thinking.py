from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

THINKING_DEPTH_DIMENSION_NAME = "思维深度"
_THINKING_ALIASES = {"思维深度", "思维含量", "思维含金量", "方法稀有度"}


def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_int(value: Any, *, default: Optional[int], min_v: int, max_v: int) -> Optional[int]:
    n = _as_int(value, default)
    if n is None:
        return None
    return max(min_v, min(max_v, n))


def _parse_dimensions(value: Any) -> List[dict]:
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    if not isinstance(raw, list):
        return []
    return [dict(x) for x in raw if isinstance(x, dict)]


def _is_thinking_dimension(name: str) -> bool:
    n = str(name or "").strip()
    if n in _THINKING_ALIASES:
        return True
    return "思维" in n and ("深" in n or "含" in n or "金" in n)


def extract_thinking_depth(dimensions: Any) -> Dict[str, Any]:
    for item in _parse_dimensions(dimensions):
        name = str(item.get("name") or "").strip()
        if not _is_thinking_dimension(name):
            continue
        return {
            "score": _clamp_int(item.get("score"), default=None, min_v=1, max_v=10),
            "comment": str(item.get("comment") or "").strip(),
            "method_family": str(item.get("method_family") or item.get("family") or "").strip(),
            "method_signature": str(item.get("method_signature") or item.get("signature") or "").strip(),
            "method_rarity": str(item.get("method_rarity") or item.get("rarity") or "").strip(),
            "similar_method_count": _as_int(
                item.get("similar_method_count")
                if item.get("similar_method_count") is not None
                else item.get("similar_count"),
                None,
            ),
        }
    return {
        "score": None,
        "comment": "",
        "method_family": "",
        "method_signature": "",
        "method_rarity": "",
        "similar_method_count": None,
    }


def build_thinking_depth_dimension(
    *,
    score: Any,
    comment: str = "",
    method_family: str = "",
    method_signature: str = "",
    method_rarity: str = "",
    similar_method_count: Any = None,
) -> Dict[str, Any]:
    return {
        "name": THINKING_DEPTH_DIMENSION_NAME,
        "score": _clamp_int(score, default=1, min_v=1, max_v=10) or 1,
        "comment": str(comment or "").strip(),
        "method_family": str(method_family or "").strip(),
        "method_signature": str(method_signature or "").strip(),
        "method_rarity": str(method_rarity or "").strip(),
        "similar_method_count": _as_int(similar_method_count, 0) or 0,
    }


def replace_thinking_depth_dimension(dimensions: Any, depth: Dict[str, Any]) -> List[dict]:
    out = []
    for item in _parse_dimensions(dimensions):
        if _is_thinking_dimension(str(item.get("name") or "")):
            continue
        out.append(item)
    out.insert(0, build_thinking_depth_dimension(**depth))
    return out


def merge_method_context(
    existing: Any,
    updates: Any,
    *,
    max_families: int = 120,
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}

    def add_one(item: Any) -> None:
        if not isinstance(item, dict):
            return
        family = str(item.get("method_family") or item.get("family") or item.get("name") or "").strip()
        if not family:
            return
        key = family.lower()
        row = merged.setdefault(
            key,
            {
                "method_family": family,
                "count": 0,
                "method_rarity": "",
                "method_signature": "",
                "example_question_ids": [],
            },
        )
        row["count"] = int(row.get("count") or 0) + max(1, _as_int(item.get("count"), 1) or 1)
        if not row.get("method_rarity"):
            row["method_rarity"] = str(item.get("method_rarity") or item.get("rarity") or "").strip()
        if not row.get("method_signature"):
            row["method_signature"] = str(item.get("method_signature") or item.get("signature") or "").strip()
        examples = item.get("example_question_ids") or item.get("examples") or []
        if isinstance(examples, list):
            seen = set(str(x) for x in row.get("example_question_ids") or [])
            for qid in examples:
                q = str(qid or "").strip()
                if not q or q in seen:
                    continue
                row["example_question_ids"].append(q)
                seen.add(q)
                if len(row["example_question_ids"]) >= 5:
                    break

    for source in (existing or [], updates or []):
        entries = source if isinstance(source, list) else []
        for entry in entries:
            add_one(entry)

    rows = list(merged.values())
    rows.sort(key=lambda x: (-int(x.get("count") or 0), str(x.get("method_family") or "")))
    return rows[: max(1, int(max_families or 120))]
