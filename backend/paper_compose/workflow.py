from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Sequence, Tuple

from sqlalchemy import desc, select

from backend.crawler_manager import get_crawler
from backend.database.models import PaperQuestion, async_session_maker, get_paper, save_paper
from backend.subjects import resolve_subject


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
    s = (stem or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"\s+", "", s)
    s = s[:1500]
    return hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()


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


def _extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


async def _load_used_question_ids(*, limit: int = 20000) -> set[str]:
    limit = max(100, int(limit or 20000))
    async with async_session_maker() as session:
        result = await session.execute(
            select(PaperQuestion.question_id).order_by(desc(PaperQuestion.id)).limit(limit)
        )
        ids = result.scalars().all()
        return {str(x).strip() for x in ids if str(x or "").strip()}


@dataclass
class _Slot:
    index: int
    question_type_raw: str
    question_type: str
    count: int
    difficulty: str
    keyword: str


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

    if not subject_input:
        yield {"type": "error", "error": "missing_subject", "taskId": task_id}
        return

    subject = resolve_subject(subject_input, strict=True)
    if not topic:
        topic = "相关知识点"

    if not paper_name:
        paper_name = f"{subject}-{topic}-组卷"

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
    if avoid_used:
        yield {
            "type": "step",
            "step": {
                "id": "load_used",
                "title": "加载历史去重集",
                "status": "running",
                "startTime": _now_iso(),
                "toolName": "compose_paper",
            },
        }
        try:
            used_ids = await _load_used_question_ids()
        except Exception:
            used_ids = set()
        yield {
            "type": "step",
            "step": {
                "id": "load_used",
                "title": "加载历史去重集",
                "status": "completed",
                "startTime": _now_iso(),
                "endTime": _now_iso(),
                "toolName": "compose_paper",
                "output": {"usedCount": len(used_ids)},
            },
        }

    slot_plans: List[_Slot] = []
    for idx, raw in enumerate(slots_in):
        if not isinstance(raw, dict):
            continue
        qtype_raw = str(raw.get("questionType") or raw.get("question_type") or "").strip()
        count = int(raw.get("count") or 0)
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

        async def _fetch(max_pages_value: int) -> Tuple[List[Dict[str, Any]], str]:
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
            )
            if not isinstance(res, dict) or not res.get("success"):
                return [], str((res or {}).get("error") or "search_failed")
            qs = res.get("questions") or []
            if not isinstance(qs, list):
                qs = []
            return [q for q in qs if isinstance(q, dict)], ""

        fetched, fetch_err = await _fetch(slot_max_pages)
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

        for q in fetched:
            qid = str(q.get("question_id") or "").strip()
            if not qid or qid in seen_candidate_ids:
                continue
            seen_candidate_ids.add(qid)
            candidates.append(q)

        def _q_quality(q: Dict[str, Any]) -> int:
            try:
                return int(q.get("quality_score") or 0)
            except Exception:
                return 0

        candidates.sort(key=_q_quality, reverse=True)

        def _select_more(remaining: int) -> List[Dict[str, Any]]:
            newly: List[Dict[str, Any]] = []
            if remaining <= 0:
                return newly
            for q in candidates:
                if len(newly) >= remaining:
                    break
                qid = str(q.get("question_id") or "").strip()
                if not qid:
                    continue
                if qid in global_seen_ids:
                    continue
                if qid in used_ids:
                    continue
                # Hard filter: avoid selecting questions that are likely unusable (login wall / broken formulas / missing options).
                flags = q.get("quality_flags") or []
                if isinstance(flags, list) and flags:
                    norm_flags = [str(x or "").strip() for x in flags if str(x or "").strip()]
                    hard_prefixes = ("formula_unconverted:", "unknown_tokens:", "choice_options_incomplete:")
                    hard_exact = {
                        "missing_stem",
                        "login_required_content",
                        "choice_missing_options",
                    }
                    if any(
                        (f in hard_exact) or f.startswith(hard_prefixes)
                        for f in norm_flags
                    ):
                        continue
                q_quality = _q_quality(q)
                if q_quality < int(quality_threshold or 0):
                    continue
                fp = ""
                if dedup_stem:
                    fp = _stem_fingerprint(str(q.get("stem") or ""))
                    if fp and fp in global_seen_fps:
                        continue
                global_seen_ids.add(qid)
                if fp:
                    global_seen_fps.add(fp)
                newly.append(q)
            return newly

        slot_selected: List[Dict[str, Any]] = []
        slot_selected.extend(_select_more(requested))
        relax_trace.append(
            {
                "action": "initial_select",
                "selected": len(slot_selected),
                "max_pages": slot_max_pages,
                "min_quality_score": quality_threshold,
                "dedup_by_stem": dedup_stem,
            }
        )

        while len(slot_selected) < requested and slot_max_pages < max_pages_cap:
            slot_max_pages = min(max_pages_cap, slot_max_pages + 2)
            fetched2, fetch_err2 = await _fetch(slot_max_pages)
            relax_trace.append({"action": "increase_max_pages", "max_pages": slot_max_pages, "success": not bool(fetch_err2)})
            if fetch_err2:
                break
            added = 0
            for q in fetched2:
                qid = str(q.get("question_id") or "").strip()
                if not qid or qid in seen_candidate_ids:
                    continue
                seen_candidate_ids.add(qid)
                candidates.append(q)
                added += 1
            if added:
                candidates.sort(key=_q_quality, reverse=True)
            slot_selected.extend(_select_more(requested - len(slot_selected)))

        while len(slot_selected) < requested and quality_threshold > quality_floor:
            quality_threshold = max(quality_floor, quality_threshold - 10)
            relax_trace.append({"action": "lower_min_quality_score", "min_quality_score": quality_threshold})
            slot_selected.extend(_select_more(requested - len(slot_selected)))

        if len(slot_selected) < requested and dedup_stem:
            dedup_stem = False
            relax_trace.append({"action": "disable_dedup_by_stem"})
            slot_selected.extend(_select_more(requested - len(slot_selected)))

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
                    ok = bool(r.get("success"))
                    lines.append(f"- 增加翻页上限到 {mp}（success={ok}）")
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
        except Exception:
            review_timeout_s = 25.0
        review_timeout_s = max(8.0, min(review_timeout_s, 120.0))

        try:
            max_stem_chars = int(os.getenv("PAPER_COMPOSE_REVIEW_MAX_STEM_CHARS") or 420)
        except Exception:
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
            import asyncio

            from backend.core.llm_client import chat_completion_text
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

                text = await asyncio.wait_for(
                    chat_completion_text(
                        messages=[
                            {"role": "system", "content": "你是严格但保守的题目匹配审查员。只输出 JSON。"},
                            {"role": "user", "content": json.dumps(slot_prompt, ensure_ascii=False)},
                        ],
                        model=review_model,
                        temperature=0.1,
                        max_tokens=900,
                        retries=2,
                        req_id_prefix="paper_review",
                    ),
                    timeout=review_timeout_s,
                )

                obj = _extract_json_obj(text)
                decisions_raw = obj.get("decisions") if isinstance(obj, dict) else None
                decisions = (
                    [x for x in (decisions_raw or []) if isinstance(x, dict)]
                    if isinstance(decisions_raw, list)
                    else []
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

    # Paper-level balance report (difficulty distribution / knowledge point repetition).
    try:
        diff_counts: Dict[str, int] = {"简单": 0, "中等": 0, "困难": 0, "未知": 0}
        kp_counts: Dict[str, int] = {}
        fp_counts: Dict[str, int] = {}
        slot_shortfalls: List[Dict[str, Any]] = []

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
            except Exception:
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
                },
            },
        }
    except Exception:
        pass

    yield {
        "type": "step",
        "step": {
            "id": "save_paper",
            "title": "保存试卷",
            "status": "running",
            "startTime": _now_iso(),
            "toolName": "create_paper",
            "input": {"paperName": paper_name, "count": len(selected_questions)},
        },
    }

    q_dicts: List[dict] = []
    for q in selected_questions:
        qid = str(q.get("question_id") or "").strip()
        if not qid:
            continue
        kps = q.get("knowledge_points")
        kp_badge = _format_kps_for_badge(kps)
        try:
            kps_json = json.dumps(kps, ensure_ascii=False) if isinstance(kps, list) else ""
        except Exception:
            kps_json = ""

        q_dicts.append(
            {
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
            }
        )

    paper_id = await save_paper(paper_name=paper_name, questions=q_dicts)
    paper = await get_paper(paper_id)
    if not paper:
        yield {"type": "error", "error": "paper_save_failed", "taskId": task_id}
        return

    yield {
        "type": "step",
        "step": {
            "id": "save_paper",
            "title": "保存试卷",
            "status": "completed",
            "startTime": _now_iso(),
            "endTime": _now_iso(),
            "toolName": "create_paper",
            "output": {"paperId": paper_id},
        },
    }

    out_paper = {
        "id": int(paper.get("paper_id") or paper_id),
        "name": str(paper.get("paper_name") or paper_name),
        "createdAt": str(paper.get("created_at") or ""),
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
