from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

FetchCandidatesFn = Callable[[int], Awaitable[Tuple[List[Dict[str, Any]], str]]]
SortCandidatesFn = Callable[[List[Dict[str, Any]]], None]
StemFingerprintFn = Callable[[str], str]
AllowCandidateFn = Callable[[Dict[str, Any]], bool]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _q_id(q: Dict[str, Any]) -> str:
    return str(q.get("question_id") or "").strip()


def _quality(q: Dict[str, Any]) -> int:
    return _safe_int(q.get("quality_score"), 0)


async def select_slot_with_relax(
    *,
    requested: int,
    candidates: List[Dict[str, Any]],
    fetch_more: FetchCandidatesFn,
    sort_candidates: Optional[SortCandidatesFn],
    global_seen_ids: Set[str],
    global_seen_fps: Set[str],
    used_ids: Optional[Set[str]] = None,
    max_pages: int,
    max_pages_cap: int,
    min_quality_score: int,
    quality_floor: int,
    dedup_by_stem: bool,
    stem_fingerprint: StemFingerprintFn,
    allow_candidate: Optional[AllowCandidateFn] = None,
    sleep_s: float = 0.0,
) -> Dict[str, Any]:
    """Select questions for a single slot with progressive relaxation.

    Relax order:
    1) Increase max_pages (+2 each time) and refetch (network)
    2) Lower min_quality_score (-10 each time) (no network)
    3) Disable dedup_by_stem (no network)
    """

    requested = max(0, int(requested or 0))
    max_pages = max(1, int(max_pages or 1))
    max_pages_cap = max(max_pages, int(max_pages_cap or max_pages))
    max_pages_cap = max(1, min(max_pages_cap, 20))

    min_quality_score = max(0, min(int(min_quality_score or 0), 100))
    quality_floor = max(0, min(int(quality_floor or 0), min_quality_score))
    dedup_by_stem = bool(dedup_by_stem)

    used_ids = used_ids or set()
    allow_candidate = allow_candidate or (lambda _q: True)
    sleep_s = float(sleep_s or 0.0)
    sleep_s = max(0.0, min(sleep_s, 3.0))

    slot_selected: List[Dict[str, Any]] = []
    relax_trace: List[Dict[str, Any]] = []

    seen_candidate_ids: Set[str] = {_q_id(q) for q in candidates if _q_id(q)}

    attempt = 1
    quality_threshold = min_quality_score

    def _trace(action: str, *, fetched: bool, fetch_success: bool, fetch_error: str = "") -> None:
        relax_trace.append(
            {
                "attempt": attempt,
                "action": action,
                "max_pages": max_pages,
                "min_quality_score": quality_threshold,
                "dedup_by_stem": dedup_by_stem,
                "fetched": fetched,
                "fetch_success": fetch_success,
                "fetch_error": fetch_error,
                "candidate_pool": len(candidates),
                "selected_total": len(slot_selected),
                "requested": requested,
            }
        )

    def _select_more(*, remaining: int) -> List[Dict[str, Any]]:
        newly: List[Dict[str, Any]] = []
        if remaining <= 0:
            return newly

        for q in candidates:
            qid = _q_id(q)
            if not qid:
                continue
            if qid in global_seen_ids:
                continue
            if qid in used_ids:
                continue
            if not allow_candidate(q):
                continue

            score = _quality(q)
            if quality_threshold > 0 and score < quality_threshold:
                continue

            fp = stem_fingerprint(str(q.get("stem") or "")) if dedup_by_stem else ""
            if dedup_by_stem and fp and fp in global_seen_fps:
                continue

            global_seen_ids.add(qid)
            if fp:
                global_seen_fps.add(fp)
            newly.append(q)
            if len(newly) >= remaining:
                break

        return newly

    # Initial select (strict, no relaxation yet)
    slot_selected.extend(_select_more(remaining=requested - len(slot_selected)))
    _trace("initial_select", fetched=False, fetch_success=True)
    attempt += 1

    # 1) Auto-expand max_pages (requires extra network calls).
    while len(slot_selected) < requested and max_pages < max_pages_cap:
        next_pages = min(max_pages_cap, max_pages + 2)
        if next_pages <= max_pages:
            break
        max_pages = next_pages

        fetched, err = await fetch_more(max_pages)
        if sleep_s > 0:
            await asyncio.sleep(sleep_s)
        if err:
            _trace("increase_max_pages", fetched=True, fetch_success=False, fetch_error=err)
            attempt += 1
            break

        added = 0
        for q in fetched:
            if not isinstance(q, dict):
                continue
            qid = _q_id(q)
            if not qid or qid in seen_candidate_ids:
                continue
            seen_candidate_ids.add(qid)
            candidates.append(q)
            added += 1
        if added and sort_candidates is not None:
            sort_candidates(candidates)

        slot_selected.extend(_select_more(remaining=requested - len(slot_selected)))
        _trace("increase_max_pages", fetched=True, fetch_success=True)
        attempt += 1

    # 2) Auto-lower min_quality_score (no network).
    while len(slot_selected) < requested and quality_threshold > quality_floor:
        quality_threshold = max(quality_floor, quality_threshold - 10)
        slot_selected.extend(_select_more(remaining=requested - len(slot_selected)))
        _trace("lower_min_quality_score", fetched=False, fetch_success=True)
        attempt += 1

    # 3) Disable dedup_by_stem for this slot (no network).
    if len(slot_selected) < requested and dedup_by_stem:
        dedup_by_stem = False
        slot_selected.extend(_select_more(remaining=requested - len(slot_selected)))
        _trace("disable_dedup_by_stem", fetched=False, fetch_success=True)
        attempt += 1

    return {
        "selected": slot_selected,
        "candidates": candidates,
        "relax_trace": relax_trace,
        "max_pages": max_pages,
        "min_quality_score": quality_threshold,
        "dedup_by_stem": dedup_by_stem,
    }
