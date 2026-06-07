from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from backend.core.logging_utils import get_logger
from backend.core.subjects import resolve_subject
from backend.integrations.crawler.manager import get_crawler
from backend.database.repositories.question.papers import add_questions_to_paper, get_paper, save_paper
from backend.database.repositories.question.question_cache import (
    get_question_cache,
    mark_used_questions,
    upsert_question_cache,
)
from backend.llm.runner import run_json
from backend.llm.prompts import create_default_prompt_registry
from backend.generation.paper_compose.answer_synthesis import synthesize_missing_answers
from backend.generation.paper_compose.ai_fill import fill_slot_with_ai
from backend.generation.paper_compose.auto_review import review_questions
from backend.generation.paper_compose.balance import apply_balance_corrections
from backend.generation.paper_compose.slot_fill import (
    allows_ai_backfill,
    allows_bank_lookup,
    fetch_local_candidates,
    normalize_source_strategy,
)
from backend.generation.paper_compose.slot_selection import select_slot_with_relax
from backend.generation.paper_compose.workflow_support import (
    _as_list,
    _clip,
    _difficulty_from_slot,
    _format_kps_for_badge,
    _kp_match_ratio,
    _load_used_question_ids,
    _normalize_question_type,
    _now_iso,
    _Slot,
    _split_kps,
    _stem_fingerprint,
    _truthy,
)

logger = get_logger(__name__)


def _question_match_reviewer_system_prompt() -> str:
    return create_default_prompt_registry().render("paper_compose.question_match_reviewer.v1").content


def _build_save_question_dicts(selected_questions: List[Dict[str, Any]], *, subject: str) -> List[dict]:
    q_dicts: List[dict] = []
    for q in selected_questions:
        qid = str(q.get("question_id") or "").strip()
        if not qid:
            continue
        kps = q.get("knowledge_points")
        kp_badge = _format_kps_for_badge(kps)
        try:
            kps_json = json.dumps(kps, ensure_ascii=False) if isinstance(kps, list) else ""
        except (TypeError, ValueError):
            kps_json = ""

        q_dicts.append(
            {
                "subject": subject,
                "question_id": qid,
                "type": str(q.get("type") or "").strip(),
                "difficulty": str(q.get("difficulty") or "").strip(),
                "difficulty_value": q.get("difficulty_value"),
                "knowledge_point": kp_badge,
                "knowledge_points_json": kps_json,
                "source_url": str(q.get("source_url") or "").strip(),
                "source": str(q.get("source") or "").strip(),
                "date": str(q.get("date") or "").strip(),
                "stem": str(q.get("stem") or "").strip(),
                "stem_fingerprint": _stem_fingerprint(str(q.get("stem") or "")),
                "quality_score": int(q.get("quality_score") or 0),
                "quality_flags": q.get("quality_flags") or [],
                "answer": str(q.get("answer") or "").strip(),
                "analysis": str(q.get("analysis") or "").strip(),
                "answer_source": str(q.get("answer_source") or "").strip(),
                "review_status": str(q.get("review_status") or "").strip(),
                "review_action": str(q.get("review_action") or "").strip(),
                "review_score": q.get("review_score"),
                "review_summary": str(q.get("review_summary") or "").strip(),
            }
        )
    return q_dicts



async def compose_paper_events(
    request: Dict[str, Any],
    *,
    user_id: str,
) -> AsyncIterator[Dict[str, Any]]:
    """Compose paper and yield timeline events for the frontend (SSE)."""

    task_id = str(request.get("taskId") or request.get("task_id") or "").strip()
    subject_input = str(request.get("subject") or "").strip()
    topic = str(request.get("topic") or "").strip()
    paper_name = str(request.get("paperName") or request.get("paper_name") or "").strip()
    mode = str(request.get("mode") or request.get("composeMode") or request.get("compose_mode") or "").strip().lower()
    existing_paper_id = int(request.get("paperId") or request.get("paper_id") or 0)
    shortfalls_in = request.get("shortfalls") or request.get("slotShortfalls") or request.get("slot_shortfalls")

    if not subject_input:
        yield {"type": "error", "error": "missing_subject", "taskId": task_id}
        return

    subject = resolve_subject(subject_input, strict=True)
    if not topic:
        topic = "相关知识点"

    required_kps = _split_kps(topic)[:6]

    if not paper_name:
        paper_name = f"{subject}-{topic}-组卷"

    existing_paper: Optional[dict] = None
    fill_shortfalls: Dict[int, int] = {}
    if mode == "fill_shortfalls":
        if existing_paper_id <= 0:
            yield {"type": "error", "error": "missing_paper_id", "taskId": task_id}
            return

        existing_paper = await get_paper(user_id=user_id, paper_id=existing_paper_id)
        if not existing_paper:
            yield {
                "type": "error",
                "error": "paper_not_found",
                "taskId": task_id,
                "data": {"paperId": existing_paper_id},
            }
            return

        paper_name = str(existing_paper.get("paper_name") or paper_name).strip() or paper_name

        items = shortfalls_in if isinstance(shortfalls_in, list) else []
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                slot_index = int(it.get("slotIndex") or it.get("slot_index") or -1)
            except (TypeError, ValueError):
                slot_index = -1
            if slot_index < 0:
                continue
            try:
                requested = int(it.get("requested") or 0)
                selected = int(it.get("selected") or 0)
            except (TypeError, ValueError):
                continue
            missing = max(0, requested - selected)
            if missing > 0:
                fill_shortfalls[slot_index] = missing

        if not fill_shortfalls:
            yield {"type": "error", "error": "no_shortfalls", "taskId": task_id, "data": {"paperId": existing_paper_id}}
            return

    filters = request.get("filters") if isinstance(request.get("filters"), dict) else {}
    grade_id = int(filters.get("gradeId") or 0) if filters else 0
    textbook_version = str(filters.get("textbookVersion") or "").strip() if filters else ""
    province_id = int(filters.get("provinceId") or -1) if filters else -1
    paper_type_id = int(filters.get("paperTypeId") or 0) if filters else 0

    options = request.get("options") if isinstance(request.get("options"), dict) else {}
    max_pages = int(options.get("maxPages") or 2)
    per_slot_expand = int(options.get("perSlotExpand") or 3)
    min_quality_score = int(options.get("minQualityScore") or 60)
    dedup_by_stem = bool(options.get("dedupByStem") if "dedupByStem" in options else True)
    avoid_used = bool(options.get("avoidUsed") if "avoidUsed" in options else True)
    source_strategy = normalize_source_strategy(options.get("sourceStrategy") or options.get("source_strategy"))
    auto_ai_backfill = _truthy(options.get("autoAiBackfill") if "autoAiBackfill" in options else "1")
    max_ai_questions_per_paper = int(options.get("maxAiQuestionsPerPaper") or 20)
    max_ai_questions_per_paper = max(0, min(max_ai_questions_per_paper, 100))
    ai_answer_synthesis = _truthy(
        options.get("aiAnswerSynthesis")
        if "aiAnswerSynthesis" in options
        else options.get("ai_answer_synthesis")
        if "ai_answer_synthesis" in options
        else os.getenv("PAPER_COMPOSE_AI_ANSWER_SYNTHESIS") or "1"
    )
    auto_review = _truthy(
        options.get("autoReview")
        if "autoReview" in options
        else options.get("auto_review")
        if "auto_review" in options
        else os.getenv("PAPER_COMPOSE_AUTO_REVIEW") or "1"
    )
    paper_balance_correction = _truthy(
        options.get("paperBalanceCorrection")
        if "paperBalanceCorrection" in options
        else options.get("paper_balance_correction")
        if "paper_balance_correction" in options
        else os.getenv("PAPER_COMPOSE_BALANCE_CORRECTION") or "1"
    )
    require_human_review = _truthy(
        options.get("requireHumanReview")
        if "requireHumanReview" in options
        else options.get("require_human_review")
        if "require_human_review" in options
        else os.getenv("PAPER_COMPOSE_REQUIRE_HUMAN_REVIEW") or "0"
    )
    judge_pass_score = int(options.get("judgePassScore") or options.get("judge_pass_score") or 65)
    judge_pass_score = max(0, min(judge_pass_score, 100))
    strict_slot_count = _truthy(
        options.get("strictSlotCount") if "strictSlotCount" in options else options.get("strict_slot_count")
    )

    slot_concurrency = int(
        options.get("slotConcurrency")
        or options.get("slot_concurrency")
        or os.getenv("PAPER_COMPOSE_SLOT_CONCURRENCY")
        or "3"
    )
    slot_concurrency = max(1, min(slot_concurrency, 10))

    candidate_parse_content = _truthy(
        options.get("candidateParseContent")
        if "candidateParseContent" in options
        else options.get("candidate_parse_content")
    )

    max_pages = max(1, min(max_pages, 8))
    per_slot_expand = max(1, min(per_slot_expand, 6))
    min_quality_score = max(0, min(min_quality_score, 100))

    slots_in = _as_list(request.get("slots"))
    if not slots_in:
        yield {"type": "error", "error": "missing_slots", "taskId": task_id}
        return

    yield {
        "type": "step",
        "step": {
            "id": "resolve_filters",
            "title": "解析筛选项",
            "status": "running",
            "startTime": _now_iso(),
            "toolName": "compose_paper",
            "input": {"subject": subject, "gradeId": grade_id, "textbookVersion": textbook_version},
        },
    }

    crawler = await get_crawler(subject=subject, edu_level="", strict=True)
    available_filters = await crawler.get_available_filters()
    question_types = available_filters.get("question_types") if isinstance(available_filters, dict) else []
    if not isinstance(question_types, list):
        question_types = []

    yield {
        "type": "step",
        "step": {
            "id": "resolve_filters",
            "title": "解析筛选项",
            "status": "completed",
            "startTime": _now_iso(),
            "endTime": _now_iso(),
            "toolName": "compose_paper",
            "output": {"questionTypes": [qt.get("name") for qt in question_types if isinstance(qt, dict)]},
        },
    }

    used_ids: set[str] = set()
    existing_ids: set[str] = set()
    if existing_paper and isinstance(existing_paper.get("questions"), list):
        for q in existing_paper.get("questions") or []:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("question_id") or "").strip()
            if qid:
                existing_ids.add(qid)
        used_ids.update(existing_ids)

    if avoid_used:
        yield {
            "type": "step",
            "step": {
                "id": "load_used",
                "title": "加载去重集（历史 + 已选题）",
                "status": "running",
                "startTime": _now_iso(),
                "toolName": "compose_paper",
            },
        }
        try:
            used_ids.update(await _load_used_question_ids(user_id=user_id, subject=subject))
        except Exception:
            logger.exception("load_used_question_ids_failed", extra={"task_id": task_id, "subject": subject})
        yield {
            "type": "step",
            "step": {
                "id": "load_used",
                "title": "加载去重集（历史 + 已选题）",
                "status": "completed",
                "startTime": _now_iso(),
                "endTime": _now_iso(),
                "toolName": "compose_paper",
                "output": {"usedCount": len(used_ids), "paperExistingCount": len(existing_ids)},
            },
        }

    slot_plans: List[_Slot] = []
    for idx, raw in enumerate(slots_in):
        if not isinstance(raw, dict):
            continue
        qtype_raw = str(raw.get("questionType") or raw.get("question_type") or "").strip()
        raw_count = int(raw.get("count") or 0)
        count = int(fill_shortfalls.get(idx) or 0) if mode == "fill_shortfalls" else raw_count
        if count <= 0:
            continue
        difficulty = _difficulty_from_slot(str(raw.get("difficulty") or ""))
        qtype = _normalize_question_type(qtype_raw, question_types)
        keyword = f"{topic} {qtype or qtype_raw}".strip()
        slot_plans.append(
            _Slot(
                index=idx,
                question_type_raw=qtype_raw,
                question_type=qtype,
                count=min(count, 50),
                difficulty=difficulty,
                keyword=keyword,
            )
        )

    if not slot_plans:
        yield {"type": "error", "error": "no_valid_slots", "taskId": task_id}
        return

    global_seen_ids: set[str] = set()
    global_seen_fps: set[str] = set()

    selected_questions: List[Dict[str, Any]] = []
    slot_results: List[Dict[str, Any]] = []
    max_pages_cap = 8
    quality_floor = 0

    fetch_sem = asyncio.Semaphore(slot_concurrency)

    async def _fetch_slot_candidates(
        slot: _Slot,
        *,
        search_limit: int,
        max_pages_value: int,
    ) -> Tuple[List[Dict[str, Any]], str]:
        async with fetch_sem:
            res = await crawler.search_by_keyword(
                keyword=slot.keyword,
                subject=subject,
                edu_level="",
                limit=search_limit,
                difficulty=slot.difficulty,
                question_type=slot.question_type,
                learn_grade_id=grade_id,
                textbook_version=textbook_version,
                max_pages=max_pages_value,
                province_id=province_id,
                paper_type_id=paper_type_id,
                dedup_by_stem=False,
                min_quality_score=0,
                with_quality=True,
                require_difficulty=True,
                strict_subject=True,
                parse_content=bool(candidate_parse_content),
            )
            if not isinstance(res, dict) or not res.get("success"):
                return [], str((res or {}).get("error") or "search_failed")
            qs = res.get("questions") or []
            if not isinstance(qs, list):
                qs = []
            return [q for q in qs if isinstance(q, dict)], ""

    prefetch_tasks: Dict[int, asyncio.Task] = {}
    if allows_bank_lookup(source_strategy) and source_strategy != "ai_first":
        for slot in slot_plans:
            requested = int(slot.count or 0)
            search_limit = min(50, max(requested * per_slot_expand, requested))
            prefetch_tasks[int(slot.index)] = asyncio.create_task(
                _fetch_slot_candidates(slot, search_limit=search_limit, max_pages_value=max_pages)
            )

    for i, slot in enumerate(slot_plans):
        step_id = f"slot-{slot.index}"
        yield {
            "type": "step",
            "step": {
                "id": step_id,
                "title": f"检索题目：{slot.question_type_raw or '题型'} × {slot.difficulty}",
                "status": "running",
                "startTime": _now_iso(),
                "toolName": "search_questions",
                "input": {"keyword": slot.keyword, "count": slot.count, "questionType": slot.question_type or ""},
            },
        }

        requested = slot.count
        search_limit = min(50, max(requested * per_slot_expand, requested))
        slot_max_pages = max_pages
        quality_threshold = min_quality_score
        dedup_stem = dedup_by_stem
        relax_trace: List[Dict[str, Any]] = []

        candidates: List[Dict[str, Any]] = []
        seen_candidate_ids: set[str] = set()
        slot_selected: List[Dict[str, Any]] = []

        def _accept_ai_items(ai_items: List[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
            accepted: List[Dict[str, Any]] = []
            for q in ai_items or []:
                if not isinstance(q, dict):
                    continue
                qid = str(q.get("question_id") or "").strip()
                if not qid or qid in global_seen_ids or qid in used_ids:
                    continue
                stem = str(q.get("stem") or "").strip()
                fp = _stem_fingerprint(stem) if dedup_by_stem else ""
                if fp and fp in global_seen_fps:
                    continue
                global_seen_ids.add(qid)
                if fp:
                    global_seen_fps.add(fp)
                q.setdefault("source", "ai_generate_full")
                q.setdefault("subject", subject)
                q.setdefault("difficulty", slot.difficulty)
                q.setdefault("question_type", slot.question_type or slot.question_type_raw)
                q.setdefault("type", slot.question_type or slot.question_type_raw)
                q.setdefault("knowledge_point", topic)
                accepted.append(q)
                if len(accepted) >= limit:
                    break
            return accepted

        async def _generate_ai_items(missing: int) -> List[Dict[str, Any]]:
            if missing <= 0:
                return []
            try:
                return await fill_slot_with_ai(
                    source_pack={"subject": subject, "topic": topic},
                    subject=subject,
                    topic=topic,
                    slot={
                        "question_type": slot.question_type or slot.question_type_raw,
                        "type": slot.question_type or slot.question_type_raw,
                        "count": missing,
                        "difficulty": slot.difficulty,
                        "keyword": slot.keyword,
                    },
                    user_id=user_id,
                    slot_index=slot.index,
                    fallback_to_crawler=False,
                )
            except Exception as exc:
                logger.warning("paper_compose_ai_backfill_failed", extra={"task_id": task_id}, exc_info=True)
                raise

        if source_strategy == "ai_first":
            remaining_ai_budget = max_ai_questions_per_paper - sum(
                1
                for q in selected_questions
                if isinstance(q, dict) and str(q.get("question_id") or "").strip().startswith("ai_")
            )
            missing = min(requested, max(0, remaining_ai_budget))
            if missing > 0:
                ai_step_id = "ai_backfill"
                yield {
                    "type": "step",
                    "step": {
                        "id": ai_step_id,
                        "title": "AI 优先生成题目",
                        "status": "running",
                        "startTime": _now_iso(),
                        "toolName": "generate_questions_ai",
                        "input": {
                            "slotIndex": slot.index,
                            "questionType": slot.question_type or slot.question_type_raw,
                            "difficulty": slot.difficulty,
                            "count": missing,
                            "sourceStrategy": source_strategy,
                        },
                    },
                }
                try:
                    ai_items = await _generate_ai_items(missing)
                except Exception as exc:
                    yield {
                        "type": "step",
                        "step": {
                            "id": ai_step_id,
                            "title": "AI 优先生成题目",
                            "status": "failed",
                            "startTime": _now_iso(),
                            "endTime": _now_iso(),
                            "toolName": "generate_questions_ai",
                            "error": str(exc),
                        },
                    }
                    ai_items = []
                accepted_ai = _accept_ai_items(ai_items, limit=missing)
                slot_selected.extend(accepted_ai)
                candidates.extend(accepted_ai)
                yield {
                    "type": "step",
                    "step": {
                        "id": ai_step_id,
                        "title": "AI 优先生成题目",
                        "status": "completed",
                        "startTime": _now_iso(),
                        "endTime": _now_iso(),
                        "toolName": "generate_questions_ai",
                        "output": {
                            "slotIndex": slot.index,
                            "requested": missing,
                            "selected": len(accepted_ai),
                            "sourceStrategy": source_strategy,
                        },
                    },
                }

        remaining_for_bank = max(0, requested - len(slot_selected))
        local_candidates: List[Dict[str, Any]] = []
        if remaining_for_bank > 0 and allows_bank_lookup(source_strategy):
            local_candidates = await fetch_local_candidates(
                user_id=user_id,
                subject=subject,
                keyword=slot.keyword,
                limit=search_limit,
                min_quality_score=min_quality_score,
            )

        if remaining_for_bank <= 0 or source_strategy == "ai_only":
            fetched, fetch_err = [], ""
        else:
            prefetch = prefetch_tasks.get(int(slot.index))
            if prefetch is not None:
                fetched, fetch_err = await prefetch
            else:
                fetched, fetch_err = await _fetch_slot_candidates(
                    slot,
                    search_limit=search_limit,
                    max_pages_value=slot_max_pages,
                )
        if fetch_err:
            yield {
                "type": "step",
                "step": {
                    "id": step_id,
                    "title": f"检索题目：{slot.question_type_raw or '题型'} × {slot.difficulty}",
                    "status": "failed",
                    "startTime": _now_iso(),
                    "endTime": _now_iso(),
                    "toolName": "search_questions",
                    "error": fetch_err,
                },
            }
            continue

        for q in [*local_candidates, *fetched]:
            qid = str(q.get("question_id") or "").strip()
            if not qid or qid in seen_candidate_ids:
                continue
            seen_candidate_ids.add(qid)
            candidates.append(q)

        # Best-effort: reuse cached metadata to avoid repeated parsing/fetching across runs.
        cache_map: Dict[str, dict] = {}
        try:
            cache_map = await get_question_cache(question_ids=list(seen_candidate_ids))
        except Exception:
            logger.warning("paper_compose_question_cache_prefetch_failed", extra={"task_id": task_id}, exc_info=True)
            cache_map = {}

        def _maybe_json_list(value: Any) -> List[str]:
            if isinstance(value, list):
                return [str(x).strip() for x in value if str(x or "").strip()]
            if isinstance(value, str):
                raw = value.strip()
                if raw.startswith("[") and raw.endswith("]"):
                    try:
                        obj = json.loads(raw)
                        if isinstance(obj, list):
                            return [str(x).strip() for x in obj if str(x or "").strip()]
                    except json.JSONDecodeError:
                        return []
            return []

        if cache_map:
            for q in candidates:
                qid = str(q.get("question_id") or "").strip()
                cached = cache_map.get(qid)
                if not isinstance(cached, dict):
                    continue

                # Prefer the longer stem snapshot (candidate stage uses preview stems by default).
                cur_stem = str(q.get("stem") or "").strip()
                cached_stem = str(cached.get("stem") or "").strip()
                if cached_stem and len(cached_stem) > len(cur_stem) + 80:
                    q["stem"] = cached_stem

                if cached.get("stem_fingerprint") and not q.get("stem_fingerprint"):
                    q["stem_fingerprint"] = cached.get("stem_fingerprint")

                # Merge answer/analysis when already cached (teacher-side local storage).
                if cached.get("answer") and not q.get("answer"):
                    q["answer"] = cached.get("answer")
                if cached.get("analysis") and not q.get("analysis"):
                    q["analysis"] = cached.get("analysis")

                if cached.get("difficulty_value") and not q.get("difficulty_value"):
                    q["difficulty_value"] = cached.get("difficulty_value")

                # knowledge_points: prefer list from cache when candidate didn't provide it.
                if not q.get("knowledge_points") and cached.get("knowledge_points_json"):
                    q["knowledge_points"] = _maybe_json_list(cached.get("knowledge_points_json"))

                # quality score/flags are useful for filtering unusable items.
                try:
                    if int(cached.get("quality_score") or 0) > int(q.get("quality_score") or 0):
                        q["quality_score"] = int(cached.get("quality_score") or 0)
                except (TypeError, ValueError):
                    logger.warning(
                        "paper_compose_quality_score_merge_failed",
                        extra={"task_id": task_id, "question_id": q.get("question_id")},
                        exc_info=True,
                    )

                if cached.get("quality_flags") and not q.get("quality_flags"):
                    try:
                        q["quality_flags"] = json.loads(cached.get("quality_flags") or "[]")
                    except (TypeError, json.JSONDecodeError):
                        q["quality_flags"] = cached.get("quality_flags")

        def _q_quality(q: Dict[str, Any]) -> int:
            try:
                return int(q.get("quality_score") or 0)
            except (TypeError, ValueError):
                return 0

        if required_kps:
            for q in candidates:
                cand_kps = _split_kps(q.get("knowledge_points"))
                q["kp_match_score"] = _kp_match_ratio(required_kps, cand_kps)
            candidates.sort(
                key=lambda q: (
                    float(q.get("kp_match_score") or 0.0),
                    _q_quality(q),
                ),
                reverse=True,
            )
        else:
            candidates.sort(key=_q_quality, reverse=True)

        def _allow_candidate(q: Dict[str, Any]) -> bool:
            # Avoid selecting questions that are likely unusable (login wall / broken formulas / missing options).
            flags = q.get("quality_flags") or []
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

        async def _fetch_more(pages: int):
            return await _fetch_slot_candidates(slot, search_limit=search_limit, max_pages_value=int(pages or 1))

        remaining_for_bank = max(0, requested - len(slot_selected))
        if remaining_for_bank > 0 and source_strategy != "ai_only":
            sel = await select_slot_with_relax(
                requested=remaining_for_bank,
                candidates=candidates,
                fetch_more=_fetch_more,
                sort_candidates=(lambda items: items.sort(key=_q_quality, reverse=True)),
                global_seen_ids=global_seen_ids,
                global_seen_fps=global_seen_fps,
                used_ids=used_ids,
                max_pages=slot_max_pages,
                max_pages_cap=max_pages_cap,
                min_quality_score=quality_threshold,
                quality_floor=quality_floor,
                dedup_by_stem=dedup_stem,
                stem_fingerprint=_stem_fingerprint,
                allow_candidate=_allow_candidate,
            )

            bank_selected = sel.get("selected") if isinstance(sel.get("selected"), list) else []
            slot_selected.extend(bank_selected)
            candidates = sel.get("candidates") if isinstance(sel.get("candidates"), list) else candidates
            relax_trace = sel.get("relax_trace") if isinstance(sel.get("relax_trace"), list) else relax_trace
            slot_max_pages = int(sel.get("max_pages") or slot_max_pages)
            quality_threshold = int(sel.get("min_quality_score") or quality_threshold)
            dedup_stem = bool(sel.get("dedup_by_stem") if "dedup_by_stem" in sel else dedup_stem)

        if len(slot_selected) < requested and allows_ai_backfill(
            source_strategy,
            auto_ai_backfill=auto_ai_backfill,
        ):
            remaining_ai_budget = max_ai_questions_per_paper - sum(
                1
                for q in selected_questions
                if isinstance(q, dict) and str(q.get("question_id") or "").strip().startswith("ai_")
            )
            missing = min(requested - len(slot_selected), max(0, remaining_ai_budget))
            if missing > 0:
                ai_step_id = "ai_backfill"
                yield {
                    "type": "step",
                    "step": {
                        "id": ai_step_id,
                        "title": "AI 补齐缺口题目",
                        "status": "running",
                        "startTime": _now_iso(),
                        "toolName": "generate_questions_ai",
                        "input": {
                            "slotIndex": slot.index,
                            "questionType": slot.question_type or slot.question_type_raw,
                            "difficulty": slot.difficulty,
                            "count": missing,
                            "sourceStrategy": source_strategy,
                        },
                    },
                }
                ai_items: List[Dict[str, Any]] = []
                try:
                    ai_items = await _generate_ai_items(missing)
                except Exception as exc:
                    yield {
                        "type": "step",
                        "step": {
                            "id": ai_step_id,
                            "title": "AI 补齐缺口题目",
                            "status": "failed",
                            "startTime": _now_iso(),
                            "endTime": _now_iso(),
                            "toolName": "generate_questions_ai",
                            "error": str(exc),
                        },
                    }
                    ai_items = []

                accepted_ai = _accept_ai_items(ai_items, limit=missing)
                slot_selected.extend(accepted_ai)
                candidates.extend(accepted_ai)
                yield {
                    "type": "step",
                    "step": {
                        "id": ai_step_id,
                        "title": "AI 补齐缺口题目",
                        "status": "completed",
                        "startTime": _now_iso(),
                        "endTime": _now_iso(),
                        "toolName": "generate_questions_ai",
                        "output": {
                            "slotIndex": slot.index,
                            "requested": missing,
                            "selected": len(accepted_ai),
                            "sourceStrategy": source_strategy,
                        },
                    },
                }

        selected_questions.extend(slot_selected)
        slot_results.append(
            {
                "slot": slot,
                "selected": slot_selected,
                "candidates": candidates,
                "quality_threshold": quality_threshold,
                "dedup_by_stem": dedup_stem,
            }
        )

        if len(relax_trace) > 1:
            lines = [
                f"选题策略说明：{slot.question_type_raw or '题型'} × {slot.difficulty}",
                f"- 需求数量：{requested}",
                f"- 实际选中：{len(slot_selected)}",
                "",
                "触发放宽条件（按顺序）：",
            ]
            for r in relax_trace[1:]:
                if not isinstance(r, dict):
                    continue
                action = str(r.get("action") or "").strip()
                if action == "increase_max_pages":
                    mp = int(r.get("max_pages") or 0)
                    ok = bool(r.get("success")) if "success" in r else bool(r.get("fetch_success"))
                    err = str(r.get("fetch_error") or "").strip()
                    suffix = f"，error={err}" if err else ""
                    lines.append(f"- 增加翻页上限到 {mp}（success={ok}{suffix}）")
                elif action == "lower_min_quality_score":
                    qs = int(r.get("min_quality_score") or 0)
                    lines.append(f"- 降低最小质量分到 {qs}")
                elif action == "disable_dedup_by_stem":
                    lines.append("- 关闭按题干去重（dedup_by_stem=false）")
                else:
                    lines.append(f"- {action or 'unknown_action'}")
            if len(slot_selected) < requested:
                lines.extend(["", "仍未选够题数：将以当前结果继续组卷（可在后续手动补齐/调整）。"])

            yield {
                "type": "step",
                "step": {
                    "id": f"{step_id}-thinking",
                    "title": "选题放宽策略（原因说明）",
                    "status": "completed",
                    "startTime": _now_iso(),
                    "endTime": _now_iso(),
                    "toolName": "thinking",
                    "output": "\n".join([x for x in lines if x is not None]),
                },
            }

        yield {
            "type": "step",
            "step": {
                "id": step_id,
                "title": f"检索题目：{slot.question_type_raw or '题型'} × {slot.difficulty}",
                "status": "completed",
                "startTime": _now_iso(),
                "endTime": _now_iso(),
                "toolName": "search_questions",
                "output": {
                    "requested": requested,
                    "selected": len(slot_selected),
                    "candidateCount": len(candidates),
                    "relaxTrace": relax_trace,
                },
            },
        }

        yield {"type": "progress", "progress": float((i + 1) / len(slot_plans) * 80.0)}

    if not selected_questions:
        yield {"type": "error", "error": "no_questions_selected", "taskId": task_id}
        return

    # Optional: review selected questions with LLM and replace obvious mismatches.
    enable_llm_review = _truthy(
        options.get("llmReview")
        or options.get("llm_review")
        or options.get("enableLLMReview")
        or options.get("enable_llm_review")
    ) or _truthy(os.getenv("PAPER_COMPOSE_LLM_REVIEW"))

    if enable_llm_review and slot_results:
        review_step_id = "review_selected_questions"
        yield {
            "type": "step",
            "step": {
                "id": review_step_id,
                "title": "LLM 审查题目匹配度（可选）",
                "status": "running",
                "startTime": _now_iso(),
                "toolName": "review_questions",
                "input": {"slots": len(slot_results), "selected": len(selected_questions)},
            },
        }

        review_model = str(os.getenv("PAPER_COMPOSE_REVIEW_MODEL") or "").strip()
        try:
            review_timeout_s = float(os.getenv("PAPER_COMPOSE_REVIEW_TIMEOUT_S") or "25")
        except (TypeError, ValueError):
            review_timeout_s = 25.0
        review_timeout_s = max(8.0, min(review_timeout_s, 120.0))

        try:
            max_stem_chars = int(os.getenv("PAPER_COMPOSE_REVIEW_MAX_STEM_CHARS") or 420)
        except (TypeError, ValueError):
            max_stem_chars = 420
        max_stem_chars = max(120, min(max_stem_chars, 1200))

        total_replaced = 0
        slot_reports: List[Dict[str, Any]] = []

        selected_ids: set[str] = set()
        selected_fps: set[str] = set()
        for q in selected_questions:
            qid = str(q.get("question_id") or "").strip()
            if qid:
                selected_ids.add(qid)
            if dedup_by_stem:
                fp = _stem_fingerprint(str(q.get("stem") or ""))
                if fp:
                    selected_fps.add(fp)

        try:
            from backend.core.settings import MAIN_MODEL

            if not review_model:
                review_model = str(MAIN_MODEL or "").strip() or "openai/gpt-5-mini"

            for sr in slot_results:
                slot_obj = sr.get("slot")
                slot_selected = sr.get("selected") if isinstance(sr.get("selected"), list) else []
                slot_candidates = sr.get("candidates") if isinstance(sr.get("candidates"), list) else []
                if not isinstance(slot_obj, _Slot) or not slot_selected:
                    continue

                slot_prompt = {
                    "subject": subject,
                    "topic": topic,
                    "slot": {
                        "question_type": slot_obj.question_type or slot_obj.question_type_raw,
                        "difficulty": slot_obj.difficulty,
                        "count": slot_obj.count,
                        "keyword": slot_obj.keyword,
                    },
                    "questions": [
                        {
                            "question_id": str(q.get("question_id") or "").strip(),
                            "type": str(q.get("type") or "").strip(),
                            "difficulty": str(q.get("difficulty") or "").strip(),
                            "knowledge_points": _as_list(q.get("knowledge_points"))[:3],
                            "stem": _clip(str(q.get("stem") or ""), max_stem_chars),
                        }
                        for q in slot_selected
                        if str(q.get("question_id") or "").strip()
                    ],
                    "instructions": [
                        "请审查每道题是否明显不匹配本 slot 的题型/难度/主题（topic）要求。",
                        "原则：保守，不要过度拒绝；只有明显不相关/题型错误/难度明显不符时才判 fail。",
                        "输出严格 JSON：{decisions:[{question_id, pass, reason}]}。",
                    ],
                }

                obj = await run_json(
                    messages=[
                        {"role": "system", "content": _question_match_reviewer_system_prompt()},
                        {"role": "user", "content": json.dumps(slot_prompt, ensure_ascii=False)},
                    ],
                    model=review_model,
                    temperature=0.1,
                    max_tokens=900,
                    retries=2,
                    timeout_s=review_timeout_s,
                    req_id_prefix="paper_review",
                )
                decisions_raw = obj.get("decisions") if isinstance(obj, dict) else None
                decisions = (
                    [x for x in (decisions_raw or []) if isinstance(x, dict)] if isinstance(decisions_raw, list) else []
                )

                decision_by_id: Dict[str, Dict[str, Any]] = {}
                for d in decisions[:50]:
                    qid = str(d.get("question_id") or "").strip()
                    if qid:
                        decision_by_id[qid] = d

                replaced: List[Dict[str, Any]] = []
                rejected = 0

                for idx, q in enumerate(list(slot_selected)):
                    qid = str(q.get("question_id") or "").strip()
                    if not qid:
                        continue
                    d = decision_by_id.get(qid) or {}
                    passed = d.get("pass")
                    if passed is True or passed is None:
                        continue
                    rejected += 1

                    new_q: Dict[str, Any] = {}
                    for cand in slot_candidates:
                        if not isinstance(cand, dict):
                            continue
                        cand_id = str(cand.get("question_id") or "").strip()
                        if not cand_id or cand_id in selected_ids or cand_id in used_ids:
                            continue
                        if slot_obj.question_type and str(cand.get("type") or "").strip() != slot_obj.question_type:
                            continue
                        if dedup_by_stem:
                            fp = _stem_fingerprint(str(cand.get("stem") or ""))
                            if fp and fp in selected_fps:
                                continue
                        cand_score = int(cand.get("quality_score") or 0)
                        if cand_score < int(min_quality_score or 0):
                            continue
                        new_q = cand
                        break

                    if not new_q:
                        continue

                    old_fp = _stem_fingerprint(str(q.get("stem") or "")) if dedup_by_stem else ""
                    slot_selected[idx] = new_q

                    selected_ids.discard(qid)
                    selected_ids.add(str(new_q.get("question_id") or "").strip())
                    if dedup_by_stem:
                        if old_fp:
                            selected_fps.discard(old_fp)
                        new_fp = _stem_fingerprint(str(new_q.get("stem") or ""))
                        if new_fp:
                            selected_fps.add(new_fp)

                    total_replaced += 1
                    replaced.append(
                        {
                            "old": qid,
                            "new": str(new_q.get("question_id") or "").strip(),
                            "reason": str(d.get("reason") or "").strip(),
                        }
                    )

                slot_reports.append(
                    {
                        "slotIndex": slot_obj.index,
                        "questionType": slot_obj.question_type_raw or slot_obj.question_type,
                        "difficulty": slot_obj.difficulty,
                        "rejected": rejected,
                        "replaced": len(replaced),
                        "replacements": replaced[:12],
                    }
                )

            # Rebuild final selection after replacements.
            selected_questions = [
                q
                for sr in slot_results
                for q in (sr.get("selected") or [])
                if isinstance(q, dict) and str(q.get("question_id") or "").strip()
            ]

            yield {
                "type": "step",
                "step": {
                    "id": review_step_id,
                    "title": "LLM 审查题目匹配度（可选）",
                    "status": "completed",
                    "startTime": _now_iso(),
                    "endTime": _now_iso(),
                    "toolName": "review_questions",
                    "output": {
                        "enabled": True,
                        "model": review_model,
                        "totalReplaced": total_replaced,
                        "slots": slot_reports,
                    },
                },
            }
        except Exception as exc:
            logger.warning("paper_compose_review_step_failed", extra={"task_id": task_id}, exc_info=True)
            # Best-effort: never block paper composing on optional review.
            yield {
                "type": "step",
                "step": {
                    "id": review_step_id,
                    "title": "LLM 审查题目匹配度（可选）",
                    "status": "completed",
                    "startTime": _now_iso(),
                    "endTime": _now_iso(),
                    "toolName": "review_questions",
                    "output": {"enabled": True, "skipped": True, "error": str(exc)},
                },
            }

    balance_correction_summary: Dict[str, Any] = {"enabled": False, "totalReplaced": 0}
    if paper_balance_correction and slot_results:
        balance_step_id = "paper_balance_correction"
        yield {
            "type": "step",
            "step": {
                "id": balance_step_id,
                "title": "整卷平衡性修正",
                "status": "running",
                "startTime": _now_iso(),
                "toolName": "paper_balance",
                "input": {"slots": len(slot_results), "selected": len(selected_questions)},
            },
        }
        try:
            balance_correction_summary = apply_balance_corrections(
                slot_results,
                used_ids=used_ids,
                stem_fingerprint=_stem_fingerprint,
                min_quality_score=min_quality_score,
            )
            selected_questions = [
                q
                for sr in slot_results
                for q in (sr.get("selected") or [])
                if isinstance(q, dict) and str(q.get("question_id") or "").strip()
            ]
        except Exception as exc:
            logger.warning("paper_compose_balance_correction_failed", extra={"task_id": task_id}, exc_info=True)
            balance_correction_summary = {"enabled": True, "skipped": True, "error": str(exc), "totalReplaced": 0}

        yield {
            "type": "step",
            "step": {
                "id": balance_step_id,
                "title": "整卷平衡性修正",
                "status": "completed",
                "startTime": _now_iso(),
                "endTime": _now_iso(),
                "toolName": "paper_balance",
                "output": balance_correction_summary,
            },
        }

    slot_shortfalls: List[Dict[str, Any]] = []

    # Paper-level balance report (difficulty distribution / knowledge point repetition).
    try:
        diff_counts: Dict[str, int] = {"简单": 0, "中等": 0, "困难": 0, "未知": 0}
        kp_counts: Dict[str, int] = {}
        fp_counts: Dict[str, int] = {}

        for sr in slot_results:
            slot_obj = sr.get("slot")
            selected = sr.get("selected") or []
            if isinstance(slot_obj, _Slot):
                requested = int(slot_obj.count or 0)
                got = len([q for q in selected if isinstance(q, dict)])
                if requested > 0 and got < requested:
                    slot_shortfalls.append(
                        {
                            "slotIndex": int(slot_obj.index),
                            "questionType": slot_obj.question_type_raw or slot_obj.question_type,
                            "difficulty": slot_obj.difficulty,
                            "requested": requested,
                            "selected": got,
                        }
                    )

        for q in selected_questions:
            if not isinstance(q, dict):
                continue
            label = str(q.get("difficulty") or "").strip()
            dv = q.get("difficulty_value")
            bucket = "未知"
            try:
                dvf = float(dv) if dv is not None and str(dv).strip() else None
            except (TypeError, ValueError):
                dvf = None
            if dvf is not None:
                if dvf <= 0.39:
                    bucket = "困难"
                elif dvf <= 0.69:
                    bucket = "中等"
                else:
                    bucket = "简单"
            else:
                if "难" in label:
                    bucket = "困难"
                elif "中" in label or "适" in label:
                    bucket = "中等"
                elif "易" in label or "简" in label:
                    bucket = "简单"
            diff_counts[bucket] = int(diff_counts.get(bucket) or 0) + 1

            fp = _stem_fingerprint(str(q.get("stem") or ""))
            if fp:
                fp_counts[fp] = int(fp_counts.get(fp) or 0) + 1

            kps = q.get("knowledge_points")
            if isinstance(kps, list):
                for kp in kps[:12]:
                    name = str(kp or "").strip()
                    if name:
                        kp_counts[name] = int(kp_counts.get(name) or 0) + 1
            else:
                name = str(kps or "").strip()
                if name:
                    kp_counts[name] = int(kp_counts.get(name) or 0) + 1

        top_kps = sorted(kp_counts.items(), key=lambda kv: (-int(kv[1]), kv[0]))[:10]
        dup_stems = sum(1 for _fp, c in fp_counts.items() if int(c) > 1)

        yield {
            "type": "step",
            "step": {
                "id": "paper_balance",
                "title": "整卷平衡性检查（可观测）",
                "status": "completed",
                "startTime": _now_iso(),
                "endTime": _now_iso(),
                "toolName": "compose_paper",
                "output": {
                    "totalSelected": len(selected_questions),
                    "difficultyBuckets": diff_counts,
                    "duplicateStemCount": dup_stems,
                    "topKnowledgePoints": [{"name": k, "count": v} for k, v in top_kps],
                    "slotShortfalls": slot_shortfalls[:12],
                    "correction": balance_correction_summary,
                },
            },
        }
    except Exception:
        logger.warning("paper_compose_balance_step_failed", extra={"task_id": task_id}, exc_info=True)

    if strict_slot_count and slot_shortfalls:
        yield {
            "type": "error",
            "error": "slot_shortfall",
            "taskId": task_id,
            "data": {
                "message": "严格模式：存在槽位缺题，未保存试卷。请调整筛选条件或点击“重试补齐”。",
                "slotShortfalls": slot_shortfalls,
            },
        }
        return

    # Best-effort: fetch richer question details (including answer/analysis when available) for selected questions.
    fetch_details = _truthy(
        options.get("fetchDetails")
        if "fetchDetails" in options
        else options.get("fetch_details")
        if "fetch_details" in options
        else os.getenv("PAPER_COMPOSE_FETCH_DETAILS") or "1"
    )

    if fetch_details and selected_questions:
        detail_step_id = "fetch_question_details"
        yield {
            "type": "step",
            "step": {
                "id": detail_step_id,
                "title": "补齐题目详情（答案/解析/题干快照）",
                "status": "running",
                "startTime": _now_iso(),
                "toolName": "batch_get_question_details",
                "input": {"count": len(selected_questions)},
            },
        }

        selected_ids = [str(q.get("question_id") or "").strip() for q in selected_questions if isinstance(q, dict)]
        selected_ids = [x for x in selected_ids if x]

        details_max_concurrent = int(
            options.get("detailsConcurrency")
            or options.get("details_concurrency")
            or os.getenv("PAPER_COMPOSE_DETAILS_CONCURRENCY")
            or "5"
        )
        details_max_concurrent = max(1, min(details_max_concurrent, 20))

        ok_n = 0
        err_n = 0
        err_samples: List[Dict[str, Any]] = []

        by_id: Dict[str, Dict[str, Any]] = {
            str(q.get("question_id") or "").strip(): q
            for q in selected_questions
            if isinstance(q, dict) and str(q.get("question_id") or "").strip()
        }

        cache_updates: List[dict] = []
        try:
            details_res = await crawler.batch_get_question_details(selected_ids, max_concurrent=details_max_concurrent)
            items = details_res.get("questions") if isinstance(details_res, dict) else []
            if not isinstance(items, list):
                items = []

            for it in items:
                if not isinstance(it, dict):
                    continue
                qid = str(it.get("question_id") or "").strip()
                if not qid:
                    continue
                if it.get("success") is True:
                    ok_n += 1
                    target = by_id.get(qid)
                    if isinstance(target, dict):
                        for k in ("type", "difficulty", "knowledge_points", "source", "date", "stem", "source_url"):
                            v = it.get(k)
                            if v is not None and str(v).strip():
                                target[k] = v
                        for k in ("answer", "analysis"):
                            v = it.get(k)
                            if v is not None and str(v).strip():
                                target[k] = v
                    cache_updates.append({**it, "subject": subject})
                else:
                    err_n += 1
                    if len(err_samples) < 6:
                        err_samples.append(
                            {
                                "question_id": qid,
                                "error": str(it.get("error") or "").strip(),
                                "login_required": bool(it.get("login_required")),
                                "cookie_expired": bool(it.get("cookie_expired")),
                            }
                        )
        except Exception as exc:
            logger.warning("paper_compose_detail_fetch_batch_failed", extra={"task_id": task_id}, exc_info=True)
            err_n = len(selected_ids)
            err_samples = [{"error": str(exc)}]

        try:
            if cache_updates:
                await upsert_question_cache(cache_updates)
        except Exception:
            logger.exception("paper_compose_question_cache_upsert_failed", extra={"task_id": task_id})

        yield {
            "type": "step",
            "step": {
                "id": detail_step_id,
                "title": "补齐题目详情（答案/解析/题干快照）",
                "status": "completed",
                "startTime": _now_iso(),
                "endTime": _now_iso(),
                "toolName": "batch_get_question_details",
                "output": {"requested": len(selected_ids), "success": ok_n, "failed": err_n, "errors": err_samples},
            },
        }

    if ai_answer_synthesis and selected_questions:
        synthesis_step_id = "answer_synthesis"
        missing_count = sum(
            1
            for q in selected_questions
            if isinstance(q, dict)
            and str(q.get("stem") or "").strip()
            and (not str(q.get("answer") or "").strip() or not str(q.get("analysis") or "").strip())
        )
        if missing_count > 0:
            yield {
                "type": "step",
                "step": {
                    "id": synthesis_step_id,
                    "title": "AI 补全答案/解析",
                    "status": "running",
                    "startTime": _now_iso(),
                    "toolName": "answer_synthesis",
                    "input": {"missing": missing_count},
                },
            }
            try:
                synthesis = await synthesize_missing_answers(
                    selected_questions,
                    subject=subject,
                    topic=topic,
                    max_items=max_ai_questions_per_paper,
                )
            except Exception as exc:
                logger.warning("paper_compose_answer_synthesis_step_failed", extra={"task_id": task_id}, exc_info=True)
                synthesis = {"updated": 0, "skipped": 0, "failed": missing_count, "error": str(exc)}
            cache_updates = [
                {**q, "subject": subject}
                for q in selected_questions
                if isinstance(q, dict) and str(q.get("answer_source") or "") == "ai_synthesis"
            ]
            if cache_updates:
                try:
                    await upsert_question_cache(cache_updates)
                except Exception:
                    logger.exception("paper_compose_answer_synthesis_cache_upsert_failed", extra={"task_id": task_id})
            yield {
                "type": "step",
                "step": {
                    "id": synthesis_step_id,
                    "title": "AI 补全答案/解析",
                    "status": "completed",
                    "startTime": _now_iso(),
                    "endTime": _now_iso(),
                    "toolName": "answer_synthesis",
                    "output": synthesis,
                },
            }

    auto_review_summary: Dict[str, Any] = {}
    if auto_review and selected_questions:
        review_step_id = "auto_review"
        yield {
            "type": "step",
            "step": {
                "id": review_step_id,
                "title": "自动审核题目质量",
                "status": "running",
                "startTime": _now_iso(),
                "toolName": "auto_review",
                "input": {"count": len(selected_questions), "judgePassScore": judge_pass_score},
            },
        }
        try:
            review_summary = await review_questions(
                selected_questions,
                subject=subject,
                topic=topic,
                judge_pass_score=judge_pass_score,
                run_llm=True,
                review_bank_questions=enable_llm_review,
                max_items=max_ai_questions_per_paper,
            )
        except Exception as exc:
            logger.warning("paper_compose_auto_review_step_failed", extra={"task_id": task_id}, exc_info=True)
            review_summary = {"passed": 0, "failed": 0, "skipped": len(selected_questions), "error": str(exc)}
        auto_review_summary = dict(review_summary) if isinstance(review_summary, dict) else {}
        yield {
            "type": "step",
            "step": {
                "id": review_step_id,
                "title": "自动审核题目质量",
                "status": "completed",
                "startTime": _now_iso(),
                "endTime": _now_iso(),
                "toolName": "auto_review",
                "output": review_summary,
            },
        }

    q_dicts = _build_save_question_dicts(selected_questions, subject=subject)

    if require_human_review:
        compose_draft = {
            "paperName": paper_name,
            "subject": subject,
            "topic": topic,
            "mode": mode,
            "paperId": existing_paper_id if mode == "fill_shortfalls" else None,
            "questions": q_dicts,
            "reviewSummary": auto_review_summary,
            "slotMapping": [
                {
                    "slotIndex": _slot_index,
                    "questionIds": [
                        str(q.get("question_id") or "").strip()
                        for q in (sr.get("selected") or [])
                        if isinstance(q, dict) and str(q.get("question_id") or "").strip()
                    ],
                }
                for sr in slot_results
                for _slot_index in [int(getattr(sr.get("slot"), "index", 0) or 0)]
            ],
        }
        yield {
            "type": "step",
            "step": {
                "id": "human_review",
                "title": "等待人工审核",
                "status": "pending_review",
                "startTime": _now_iso(),
                "endTime": _now_iso(),
                "toolName": "compose-review",
                "output": {
                    "questionCount": len(q_dicts),
                    "reviewSummary": auto_review_summary,
                },
            },
        }
        yield {"type": "pending_review", "taskId": task_id, "composeDraft": compose_draft}
        return

    save_title = "保存试卷" if mode != "fill_shortfalls" else "补齐试卷（追加题目）"
    save_tool = "create_paper" if mode != "fill_shortfalls" else "update_paper"
    save_input = {"paperName": paper_name, "count": len(selected_questions)}
    if mode == "fill_shortfalls":
        save_input["paperId"] = existing_paper_id

    yield {
        "type": "step",
        "step": {
            "id": "save_paper",
            "title": save_title,
            "status": "running",
            "startTime": _now_iso(),
            "toolName": save_tool,
            "input": save_input,
        },
    }

    if mode == "fill_shortfalls":
        await add_questions_to_paper(user_id=user_id, paper_id=existing_paper_id, questions=q_dicts)
        paper_id = int(existing_paper_id)
    else:
        paper_id = await save_paper(user_id=user_id, paper_name=paper_name, questions=q_dicts)
    try:
        await mark_used_questions(
            question_ids=[q.get("question_id") for q in q_dicts if isinstance(q, dict)],
            subject=subject,
            user_id=user_id,
        )
    except Exception:
        logger.exception("mark_used_questions_failed", extra={"task_id": task_id, "paper_id": paper_id})
    paper = await get_paper(user_id=user_id, paper_id=paper_id)
    if not paper:
        yield {"type": "error", "error": "paper_save_failed", "taskId": task_id}
        return

    yield {
        "type": "step",
        "step": {
            "id": "save_paper",
            "title": save_title,
            "status": "completed",
            "startTime": _now_iso(),
            "endTime": _now_iso(),
            "toolName": save_tool,
            "output": {"paperId": paper_id, "appended": len(q_dicts) if mode == "fill_shortfalls" else None},
        },
    }

    out_paper = {
        "id": int(paper.get("paper_id") or paper_id),
        "name": str(paper.get("paper_name") or paper_name),
        "createdAt": str(paper.get("created_at") or ""),
        "sourceMode": str(paper.get("source_mode") or ""),
        "questions": [
            {
                "questionId": str(q.get("question_id") or ""),
                "order": q.get("order"),
                "type": q.get("type"),
                "difficulty": q.get("difficulty"),
                "knowledgePoint": q.get("knowledge_point"),
                "sourceUrl": q.get("source_url"),
                "stem": q.get("stem") or "",
            }
            for q in (paper.get("questions") or [])
            if isinstance(q, dict) and str(q.get("question_id") or "").strip()
        ],
    }

    yield {"type": "progress", "progress": 100.0}
    yield {"type": "result", "result": out_paper}
