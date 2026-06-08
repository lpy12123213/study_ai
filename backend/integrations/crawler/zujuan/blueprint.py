"""Zujuan blueprint composition helper."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.integrations.crawler.zujuan.utils import (
    _safe_int,
)
from backend.generation.paper_compose.slot_selection import select_slot_with_relax


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
    parts = re.split(r"[,，;；|、/\n\r\t]+", s)
    return [p.strip() for p in parts if p.strip()]


async def compose_paper_blueprint(
    self,
    blueprint: List[Dict[str, Any]],
    *,
    subject: str = "",
    edu_level: str = "",
    learn_grade: str = "",
    learn_grade_id: int = 0,
    textbook_version: str = "",
    elective_mode: str = "",
    elective_keywords: Optional[List[str]] = None,
    exclude_elective: bool = False,
    year: int = 0,
    province: str = "",
    province_id: int = -1,
    paper_type_id: int = 0,
    term: int = 0,
    order_by: int = 2,
    max_pages: int = 2,
    per_slot_expand: int = 3,
    min_quality_score: int = 0,
    dedup_by_stem: bool = True,
    strict_subject: bool = True,
    slot_concurrency: int = 0,
    slot_delay_s: float = 0.0,
    slot_retries: int = 1,
) -> Dict[str, Any]:
    """
    根据蓝图（多个“检索槽位”）批量检索并组装题目列表。

    blueprint 每项示例：
    {
      "keyword": "阅读理解",
      "count": 4,
      "difficulty": "中等",
      "question_type": "",
      "source_contains": "",
      "stem_contains": "",
      "knowledge_contains": ""
    }
    """
    if not isinstance(blueprint, list) or not blueprint:
        return {"success": False, "error": "blueprint 不能为空"}

    per_slot_expand = _safe_int(per_slot_expand, 3)
    per_slot_expand = max(1, min(6, per_slot_expand))

    max_pages_default = _safe_int(max_pages, 2)
    max_pages_default = max(1, min(8, max_pages_default))
    max_pages_cap = 8

    min_quality_score = _safe_int(min_quality_score, 0)
    min_quality_floor = 0

    global_seen_ids: set[str] = set()
    global_seen_fps: set[str] = set()

    selected_questions: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []

    slot_items: List[Dict[str, Any]] = []
    for idx, slot in enumerate(blueprint):
        if not isinstance(slot, dict):
            continue

        slot_keyword = (slot.get("keyword") or "").strip()
        slot_knowledge_point = (slot.get("knowledge_point") or "").strip()
        count = _safe_int(slot.get("count"), 0)
        if count <= 0 or (not slot_keyword and not slot_knowledge_point):
            continue

        slot_max_pages = _safe_int(slot.get("max_pages"), 0) or max_pages_default
        slot_max_pages = max(1, min(max_pages_cap, slot_max_pages))

        search_limit = max(count * per_slot_expand, count)
        search_limit = min(search_limit, 50)

        slot_items.append(
            {
                "index": idx,
                "slot": slot,
                "keyword": slot_keyword,
                "knowledge_point": slot_knowledge_point,
                "requested": count,
                "difficulty": (slot.get("difficulty") or "").strip(),
                "question_type": (slot.get("question_type") or "").strip(),
                "source_contains": (slot.get("source_contains") or "").strip(),
                "stem_contains": (slot.get("stem_contains") or "").strip(),
                "knowledge_contains": (slot.get("knowledge_contains") or "").strip(),
                "max_pages": slot_max_pages,
                "search_limit": search_limit,
            }
        )

    if not slot_items:
        return {
            "success": True,
            "count": 0,
            "question_ids": [],
            "sections": [],
            "questions_preview": [],
        }

    def _required_kps(slot_item: Dict[str, Any]) -> List[str]:
        raw = str(slot_item.get("knowledge_point") or slot_item.get("knowledge_contains") or "").strip()
        return _split_kps(raw)[:6]

    def _kp_match_ratio(required: List[str], candidate: List[str]) -> float:
        if not required:
            return 0.0
        if not candidate:
            return 0.0
        hit = 0
        for r in required:
            if any((r in c) or (c in r) for c in candidate):
                hit += 1
        return float(hit) / float(max(1, len(required)))

    def _sort_candidates(cands: List[Dict[str, Any]], *, required_kps: List[str]) -> List[Dict[str, Any]]:
        if required_kps:
            for q in cands:
                cand_kps = _split_kps(q.get("knowledge_points"))
                q["kp_match_score"] = _kp_match_ratio(required_kps, cand_kps)
            cands.sort(
                key=lambda q: (
                    float(q.get("kp_match_score") or 0.0),
                    _safe_int(q.get("quality_score"), 0),
                ),
                reverse=True,
            )
            return cands

        cands.sort(key=lambda q: _safe_int(q.get("quality_score"), 0), reverse=True)
        return cands

    async def _run_slot_search(slot_item: Dict[str, Any], *, slot_max_pages: int) -> Dict[str, Any]:
        """
        Fetch a wider candidate pool for a slot.

        Important:
        - We always fetch with `min_quality_score=0` and `dedup_by_stem=False`,
          then apply quality/dedup constraints locally in the blueprint composer,
          so later "auto relax" steps don't need extra network calls (except max_pages).
        """
        common_kwargs = dict(
            subject=subject,
            edu_level=edu_level,
            limit=slot_item["search_limit"],
            difficulty=slot_item["difficulty"],
            question_type=slot_item["question_type"],
            learn_grade=learn_grade,
            learn_grade_id=learn_grade_id,
            textbook_version=textbook_version,
            max_pages=slot_max_pages,
            year=year,
            province=province,
            province_id=province_id,
            paper_type_id=paper_type_id,
            term=term,
            order_by=order_by,
            source_contains=slot_item["source_contains"],
            stem_contains=slot_item["stem_contains"],
            knowledge_contains=slot_item["knowledge_contains"],
            require_difficulty=True,
            strict_subject=strict_subject,
            elective_mode=elective_mode,
            elective_keywords=elective_keywords,
            exclude_elective=exclude_elective,
            dedup_by_stem=False,
            min_quality_score=0,
            with_quality=True,
        )
        if slot_item["keyword"]:
            return await self.search_by_keyword(keyword=slot_item["keyword"], **common_kwargs)
        return await self.search_by_knowledge(knowledge_point=slot_item["knowledge_point"], **common_kwargs)

    slot_retries_env = _safe_int(os.getenv("ZUJUAN_BLUEPRINT_SLOT_RETRIES"), 0)
    slot_retries_value = _safe_int(slot_retries, 0) or slot_retries_env or 1
    slot_retries_value = max(1, min(slot_retries_value, 5))

    async def _run_slot_search_with_retry(slot_item: Dict[str, Any], *, slot_max_pages: int) -> Dict[str, Any]:
        last: Dict[str, Any] = {}

        for attempt in range(1, slot_retries_value + 1):
            res = await _run_slot_search(slot_item, slot_max_pages=slot_max_pages)
            if isinstance(res, dict) and res.get("success"):
                return res
            last = res if isinstance(res, dict) else {"success": False, "error": "search_failed"}
            if attempt < slot_retries_value:
                await asyncio.sleep(0.35 * attempt)
        return last

    slot_concurrency_env = _safe_int(os.getenv("ZUJUAN_BLUEPRINT_SLOT_CONCURRENCY"), 0)
    slot_concurrency_value = _safe_int(slot_concurrency, 0) or slot_concurrency_env or 3
    slot_concurrency_value = max(1, min(slot_concurrency_value, 8))

    delay_env_raw = os.getenv("ZUJUAN_BLUEPRINT_SLOT_DELAY_S") or ""
    try:
        delay_env = float(delay_env_raw) if delay_env_raw.strip() else 0.0
    except ValueError:
        delay_env = 0.0
    slot_delay_value = float(slot_delay_s or 0.0)
    if slot_delay_value <= 0:
        slot_delay_value = delay_env
    slot_delay_value = max(0.0, min(slot_delay_value, 3.0))

    sem = asyncio.Semaphore(slot_concurrency_value)

    async def _prefetch_one(slot_item: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            result = await _run_slot_search_with_retry(slot_item, slot_max_pages=slot_item["max_pages"])
            if slot_delay_value > 0:
                await asyncio.sleep(slot_delay_value)
            candidates = list(result.get("questions") or [])
            _sort_candidates(candidates, required_kps=_required_kps(slot_item))
            return {
                "success": bool(result.get("success")),
                "error": result.get("error") or "",
                "candidates": candidates,
                "trace": result.get("trace"),
            }

    prefetch_results = await asyncio.gather(
        *[asyncio.create_task(_prefetch_one(s)) for s in slot_items],
        return_exceptions=True,
    )

    prefetched_by_index: Dict[int, Dict[str, Any]] = {}
    for slot_item, res in zip(slot_items, prefetch_results):
        idx = slot_item["index"]
        if isinstance(res, Exception):
            prefetched_by_index[idx] = {
                "success": False,
                "error": str(res),
                "candidates": [],
                "trace": None,
            }
        else:
            prefetched_by_index[idx] = res

    def _allow_candidate(question: Dict[str, Any]) -> bool:
        # Keep consistent with `paper_compose.workflow` selection logic.
        flags = question.get("quality_flags") or []
        if isinstance(flags, list) and flags:
            norm_flags = [str(x or "").strip() for x in flags if str(x or "").strip()]
            hard_prefixes = ("formula_unconverted:", "unknown_tokens:", "choice_options_incomplete:")
            hard_exact = {
                "missing_stem",
                "login_required_content",
                "choice_missing_options",
            }
            if any((f in hard_exact) or f.startswith(hard_prefixes) for f in norm_flags):
                return False
        return True

    for slot_item in slot_items:
        idx = slot_item["index"]
        requested = slot_item["requested"]

        # Start from prefetched candidates if available; if prefetch failed, we can still try in-band later.
        pre = prefetched_by_index.get(idx) or {}
        candidates: List[Dict[str, Any]] = list(pre.get("candidates") or [])
        required_kps = _required_kps(slot_item)

        # If prefetch failed (or returned empty), fetch once in-band.
        if not candidates:
            initial = await _run_slot_search_with_retry(slot_item, slot_max_pages=slot_item["max_pages"])
            if slot_delay_value > 0:
                await asyncio.sleep(slot_delay_value)
            if not initial.get("success"):
                sections.append(
                    {
                        "index": idx,
                        "slot": slot_item["slot"],
                        "success": False,
                        "error": initial.get("error") or "search_failed",
                        "requested": requested,
                        "selected": 0,
                        "question_ids": [],
                        "relax_trace": [],
                    }
                )
                continue

            candidates = list(initial.get("questions") or [])
            _sort_candidates(candidates, required_kps=required_kps)

        def _sort_in_place(cands: List[Dict[str, Any]]) -> None:
            _sort_candidates(cands, required_kps=required_kps)

        async def _fetch_more(pages: int) -> Tuple[List[Dict[str, Any]], str]:
            expanded = await _run_slot_search_with_retry(slot_item, slot_max_pages=int(pages or 1))
            if not expanded.get("success"):
                return [], str(expanded.get("error") or "search_failed")
            return list(expanded.get("questions") or []), ""

        sel = await select_slot_with_relax(
            requested=requested,
            candidates=candidates,
            fetch_more=_fetch_more,
            sort_candidates=_sort_in_place,
            global_seen_ids=global_seen_ids,
            global_seen_fps=global_seen_fps,
            used_ids=set(),
            max_pages=slot_item["max_pages"],
            max_pages_cap=max_pages_cap,
            min_quality_score=min_quality_score,
            quality_floor=min_quality_floor,
            dedup_by_stem=dedup_by_stem,
            stem_fingerprint=self._stem_fingerprint,
            allow_candidate=_allow_candidate,
            sleep_s=slot_delay_value,
        )

        slot_selected: List[Dict[str, Any]] = list(sel.get("selected") or [])
        relax_trace: List[Dict[str, Any]] = list(sel.get("relax_trace") or [])

        selected_questions.extend(slot_selected)
        sections.append(
            {
                "index": idx,
                "slot": slot_item["slot"],
                "success": True,
                "requested": requested,
                "selected": len(slot_selected),
                "question_ids": [q.get("question_id") for q in slot_selected if q.get("question_id")],
                "relax_trace": relax_trace,
            }
        )

    question_ids = [q.get("question_id") for q in selected_questions if q.get("question_id")]
    return {
        "success": True,
        "count": len(question_ids),
        "question_ids": question_ids,
        "sections": sections,
        "trace": {
            "slot_concurrency": slot_concurrency_value,
            "slot_delay_s": slot_delay_value,
            "slot_retries": slot_retries_value,
            "knowledge_point_rerank": True,
        },
        # 返回精简预览，避免输出过大
        "questions_preview": [
            {
                "question_id": q.get("question_id"),
                "type": q.get("type"),
                "difficulty": q.get("difficulty"),
                "difficulty_value": q.get("difficulty_value"),
                "source": q.get("source"),
                "date": q.get("date"),
                "source_url": q.get("source_url")
                or (f"https://zujuan.xkw.com/q/{q.get('question_id')}" if q.get("question_id") else ""),
                "quality_score": q.get("quality_score"),
                "quality_flags": q.get("quality_flags", []),
            }
            for q in selected_questions
        ],
    }
