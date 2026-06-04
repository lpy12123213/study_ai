from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.core.logging_utils import get_logger
from backend.database.repositories.question.question_cache import get_question_cache
from backend.database.repositories.question.question_library import list_question_library_items

logger = get_logger(__name__)

SourceStrategy = str

_VALID_SOURCE_STRATEGIES = {"bank_first", "bank_only", "ai_first", "ai_only"}


def normalize_source_strategy(value: Any) -> SourceStrategy:
    raw = str(value or "").strip().lower()
    if raw in _VALID_SOURCE_STRATEGIES:
        return raw
    return "bank_first"


def allows_bank_lookup(strategy: SourceStrategy) -> bool:
    return strategy in {"bank_first", "bank_only", "ai_first"}


def allows_ai_backfill(strategy: SourceStrategy, *, auto_ai_backfill: bool = True) -> bool:
    if strategy == "bank_only":
        return False
    if strategy == "ai_only":
        return True
    return bool(auto_ai_backfill)


def _json_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x or "").strip()]
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("[") and raw.endswith("]"):
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                return []
            if isinstance(obj, list):
                return [str(x).strip() for x in obj if str(x or "").strip()]
        if raw:
            return [raw]
    return []


def merge_cached_question_snapshot(item: Dict[str, Any], cached: Dict[str, Any] | None) -> Dict[str, Any]:
    out = dict(item or {})
    if not isinstance(cached, dict):
        return out

    for key in (
        "subject",
        "question_type",
        "difficulty",
        "difficulty_value",
        "knowledge_point",
        "source_url",
        "stem",
        "stem_fingerprint",
        "answer",
        "analysis",
        "quality_score",
        "quality_flags",
        "source",
        "date",
    ):
        value = cached.get(key)
        if value is not None and str(value).strip():
            out[key] = value

    if cached.get("knowledge_points_json") and not out.get("knowledge_points"):
        out["knowledge_points"] = _json_list(cached.get("knowledge_points_json"))
        out["knowledge_points_json"] = cached.get("knowledge_points_json")

    return out


async def fetch_local_candidates(
    *,
    user_id: str,
    subject: str,
    keyword: str,
    limit: int,
    min_quality_score: int = 0,
) -> List[Dict[str, Any]]:
    """Fetch user-owned question-library candidates and align them to paper workflow dicts."""

    lim = max(1, min(int(limit or 1), 200))
    try:
        result = await list_question_library_items(
            user_id=user_id,
            subject=subject,
            hidden="0",
            q=str(keyword or "").strip(),
            sort="ai_score",
            order="desc",
            limit=lim,
            include_total=False,
        )
    except (RuntimeError, TypeError, ValueError, OSError):
        logger.warning("paper_compose_local_candidates_failed", exc_info=True, extra={"subject": subject})
        return []

    rows = result.get("items") if isinstance(result, dict) else []
    if not isinstance(rows, list):
        return []

    ids = [str((row or {}).get("question_id") or "").strip() for row in rows if isinstance(row, dict)]
    cache_map: Dict[str, dict] = {}
    try:
        cache_map = await get_question_cache(question_ids=ids)
    except (RuntimeError, TypeError, ValueError, OSError):
        logger.warning("paper_compose_local_cache_prefetch_failed", exc_info=True, extra={"subject": subject})
        cache_map = {}

    candidates: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        qid = str(row.get("question_id") or "").strip()
        if not qid:
            continue
        merged = merge_cached_question_snapshot(row, cache_map.get(qid))
        try:
            quality = int(merged.get("quality_score") or 0)
        except (TypeError, ValueError):
            quality = 0
        if min_quality_score > 0 and quality and quality < min_quality_score:
            continue
        qtype = str(merged.get("question_type") or merged.get("type") or "").strip()
        candidate = {
            "question_id": qid,
            "subject": str(merged.get("subject") or subject or "").strip(),
            "type": qtype,
            "question_type": qtype,
            "difficulty": str(merged.get("difficulty") or "").strip(),
            "difficulty_value": merged.get("difficulty_value"),
            "knowledge_point": str(merged.get("knowledge_point") or "").strip(),
            "knowledge_points": merged.get("knowledge_points") or _json_list(merged.get("knowledge_points_json")),
            "knowledge_points_json": merged.get("knowledge_points_json") or "",
            "source_url": str(merged.get("source_url") or "").strip(),
            "stem": str(merged.get("stem") or "").strip(),
            "stem_fingerprint": str(merged.get("stem_fingerprint") or "").strip(),
            "answer": str(merged.get("answer") or "").strip(),
            "analysis": str(merged.get("analysis") or "").strip(),
            "quality_score": quality,
            "quality_flags": merged.get("quality_flags") or [],
            "source": str(merged.get("source") or "local_question_library").strip() or "local_question_library",
            "date": str(merged.get("date") or "").strip(),
        }
        candidates.append(candidate)
        if len(candidates) >= lim:
            break

    return candidates
