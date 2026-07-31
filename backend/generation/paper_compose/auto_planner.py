from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.core.settings import LESSON_PLAN_MODEL
from backend.core.subjects import resolve_subject
from backend.generation.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.generation.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.generation.question_library.subject_knowledge import infer_subject_family
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry


def _slot_points_total(slots: List[dict]) -> int:
    total = 0
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        try:
            count = int(slot.get("count") or 0)
            points_each = int(slot.get("points_each") or slot.get("points") or 0)
        except (TypeError, ValueError):
            continue
        if count > 0 and points_each > 0:
            total += count * points_each
    return total


def _normalize_slot_points(slots: List[dict], *, total_points: int) -> tuple[List[dict], List[str]]:
    target = int(total_points or 0)
    normalized = [dict(slot) for slot in slots if isinstance(slot, dict)]
    if target <= 0 or not normalized:
        return normalized, []

    current_total = _slot_points_total(normalized)
    if current_total <= 0:
        for slot in normalized:
            try:
                count = max(1, int(slot.get("count") or 0))
            except (TypeError, ValueError):
                count = 1
            slot["points_each"] = max(1, min(60, round(target / max(1, len(normalized) * count))))
    elif current_total != target:
        scale = target / max(1, current_total)
        for slot in normalized:
            try:
                pts = int(slot.get("points_each") or slot.get("points") or 0)
            except (TypeError, ValueError):
                pts = 0
            slot["points_each"] = max(1, min(60, int(round(pts * scale)) or 1))

    def _adjust_once(diff: int) -> bool:
        candidates: list[tuple[int, int]] = []
        for idx, slot in enumerate(normalized):
            try:
                count = int(slot.get("count") or 0)
                pts = int(slot.get("points_each") or 0)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
            if diff > 0 and pts < 60 and count <= diff:
                candidates.append((count, idx))
            elif diff < 0 and pts > 1 and count <= abs(diff):
                candidates.append((count, idx))
        if not candidates:
            return False
        _count, idx = max(candidates)
        slot = normalized[idx]
        slot["points_each"] = int(slot.get("points_each") or 0) + (1 if diff > 0 else -1)
        return True

    for _ in range(1000):
        diff = target - _slot_points_total(normalized)
        if diff == 0:
            break
        if not _adjust_once(diff):
            break

    final_total = _slot_points_total(normalized)
    if final_total == target:
        return normalized, [f"score_total_normalized:{current_total}->{target}"] if current_total != target else []
    return normalized, [f"score_total_mismatch:{final_total}!={target}"]


def _finalize_structure(structure: dict, *, total_points: int) -> dict:
    slots = structure.get("slots") if isinstance(structure.get("slots"), list) else []
    normalized_slots, point_notes = _normalize_slot_points(slots, total_points=total_points)
    notes = [str(x).strip() for x in (structure.get("notes") or []) if str(x or "").strip()]
    return {"slots": normalized_slots, "notes": [*notes, *point_notes][:12]}


def get_default_paper_structure(subject: str) -> dict:
    """Fallback paper structure for 6 subject families.

    Returns:
      {
        "slots": [
          {"question_type": "...", "count": 12, "difficulty": "中等", "points_each": 5, "keyword": "", "knowledge_points": []}
        ]
      }
    """

    fam = infer_subject_family(subject)
    if fam == "math":
        return {
            "slots": [
                {"question_type": "单选题", "count": 12, "difficulty": "中等", "points_each": 5, "keyword": "", "knowledge_points": []},
                {"question_type": "填空题", "count": 4, "difficulty": "中等偏难", "points_each": 5, "keyword": "", "knowledge_points": []},
                {"question_type": "解答题", "count": 6, "difficulty": "中等偏难", "points_each": 12, "keyword": "", "knowledge_points": []},
            ]
        }
    if fam == "physics":
        return {
            "slots": [
                {"question_type": "单选题", "count": 8, "difficulty": "中等", "points_each": 4, "keyword": "", "knowledge_points": []},
                {"question_type": "实验题", "count": 2, "difficulty": "中等偏难", "points_each": 10, "keyword": "", "knowledge_points": []},
                {"question_type": "计算题", "count": 4, "difficulty": "中等偏难", "points_each": 12, "keyword": "", "knowledge_points": []},
            ]
        }
    if fam == "chemistry":
        return {
            "slots": [
                {"question_type": "单选题", "count": 10, "difficulty": "中等", "points_each": 4, "keyword": "", "knowledge_points": []},
                {"question_type": "填空题", "count": 4, "difficulty": "中等", "points_each": 5, "keyword": "", "knowledge_points": []},
                {"question_type": "实验探究题", "count": 2, "difficulty": "中等偏难", "points_each": 12, "keyword": "", "knowledge_points": []},
                {"question_type": "综合题", "count": 2, "difficulty": "中等偏难", "points_each": 14, "keyword": "", "knowledge_points": []},
            ]
        }
    if fam == "biology":
        return {
            "slots": [
                {"question_type": "单选题", "count": 12, "difficulty": "中等", "points_each": 3, "keyword": "", "knowledge_points": []},
                {"question_type": "非选择题", "count": 4, "difficulty": "中等偏难", "points_each": 12, "keyword": "", "knowledge_points": []},
            ]
        }
    if fam == "chinese":
        return {
            "slots": [
                {"question_type": "现代文阅读", "count": 2, "difficulty": "中等", "points_each": 18, "keyword": "", "knowledge_points": []},
                {"question_type": "文言文阅读", "count": 1, "difficulty": "中等", "points_each": 19, "keyword": "", "knowledge_points": []},
                {"question_type": "古诗鉴赏", "count": 1, "difficulty": "中等", "points_each": 9, "keyword": "", "knowledge_points": []},
                {"question_type": "语言文字运用", "count": 1, "difficulty": "中等", "points_each": 20, "keyword": "", "knowledge_points": []},
                {"question_type": "写作", "count": 1, "difficulty": "中等", "points_each": 60, "keyword": "", "knowledge_points": []},
            ]
        }
    if fam == "english":
        return {
            "slots": [
                {"question_type": "阅读理解", "count": 4, "difficulty": "中等", "points_each": 10, "keyword": "", "knowledge_points": []},
                {"question_type": "完形填空", "count": 1, "difficulty": "中等", "points_each": 15, "keyword": "", "knowledge_points": []},
                {"question_type": "语法填空", "count": 1, "difficulty": "中等", "points_each": 15, "keyword": "", "knowledge_points": []},
                {"question_type": "应用文写作", "count": 1, "difficulty": "中等", "points_each": 15, "keyword": "", "knowledge_points": []},
                {"question_type": "读后续写", "count": 1, "difficulty": "中等偏难", "points_each": 40, "keyword": "", "knowledge_points": []},
            ]
        }
    return {
        "slots": [
            {"question_type": "综合题", "count": 10, "difficulty": "中等", "points_each": 10, "keyword": "", "knowledge_points": []}
        ]
    }


def _structure_planner_system_prompt() -> str:
    return create_default_prompt_registry().render("paper_compose.structure_planner.v1").content


async def plan_exam_structure(
    *,
    subject: str,
    topic: str,
    total_points: int = 150,
    time_limit: int = 120,
    difficulty_distribution: Optional[dict] = None,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    """LLM-based planner with fallback to hardcoded templates."""

    subj_input = str(subject or "").strip()
    if not subj_input:
        return _finalize_structure(get_default_paper_structure("高中数学"), total_points=total_points)

    try:
        resolved_subject = resolve_subject(subj_input, strict=True)
    except ValueError:
        resolved_subject = subj_input

    if not is_llm_configured():
        return _finalize_structure(get_default_paper_structure(resolved_subject), total_points=total_points)

    payload: Dict[str, Any] = {
        "subject": resolved_subject,
        "topic": str(topic or "").strip(),
        "total_points": int(total_points or 0),
        "time_limit_minutes": int(time_limit or 0),
        "difficulty_distribution": difficulty_distribution if isinstance(difficulty_distribution, dict) else {},
        "fallback_template": get_default_paper_structure(resolved_subject),
        "output_schema": {
            "slots": [
                {
                    "question_type": "string",
                    "count": "int",
                    "difficulty": "string (简单|中等|偏难|困难)",
                    "points_each": "int",
                    "keyword": "string (optional, used for search/fill)",
                    "knowledge_points": "string[] (optional)",
                }
            ],
            "notes": "string[] (optional)",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {"role": "system", "content": _structure_planner_system_prompt()},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=0,
        req_id_prefix="paper_plan",
        retries=2,
        raise_on_fail=False,
        stage_id="plan_structure",
        stage_label="结构规划",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    slots = obj.get("slots") if isinstance(obj.get("slots"), list) else None
    if not isinstance(slots, list) or not slots:
        return _finalize_structure(get_default_paper_structure(resolved_subject), total_points=total_points)

    normalized_slots: List[dict] = []
    for s in slots:
        if not isinstance(s, dict):
            continue
        qt = str(s.get("question_type") or s.get("type") or "").strip()
        if not qt:
            continue
        try:
            cnt = int(s.get("count") or 0)
        except (TypeError, ValueError):
            cnt = 0
        if cnt <= 0:
            continue
        diff = str(s.get("difficulty") or "").strip() or "中等"
        try:
            pts = int(s.get("points_each") or s.get("points") or 0)
        except (TypeError, ValueError):
            pts = 0
        pts = max(0, min(pts, 60))
        keyword = str(s.get("keyword") or "").strip()
        kps = s.get("knowledge_points")
        kps_list = [str(x).strip() for x in (kps or []) if str(x or "").strip()] if isinstance(kps, list) else []
        normalized_slots.append(
            {
                "question_type": qt,
                "count": cnt,
                "difficulty": diff,
                "points_each": pts,
                "keyword": _clip(keyword, 80),
                "knowledge_points": kps_list[:6],
            }
        )
        if len(normalized_slots) >= 10:
            break

    if not normalized_slots:
        return _finalize_structure(get_default_paper_structure(resolved_subject), total_points=total_points)

    return _finalize_structure(
        {"slots": normalized_slots, "notes": [str(x).strip() for x in (obj.get("notes") or []) if str(x or "").strip()][:8]},
        total_points=total_points,
    )
