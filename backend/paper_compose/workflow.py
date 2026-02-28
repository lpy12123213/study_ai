from __future__ import annotations

import hashlib
import json
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

