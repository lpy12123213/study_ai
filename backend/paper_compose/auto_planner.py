from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.core.settings import LESSON_PLAN_MODEL
from backend.core.subjects import resolve_subject
from backend.llm.client import is_llm_configured
from backend.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.question_library.subject_knowledge import infer_subject_family


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
        return get_default_paper_structure("高中数学")

    try:
        resolved_subject = resolve_subject(subj_input, strict=True)
    except ValueError:
        resolved_subject = subj_input

    if not is_llm_configured():
        return get_default_paper_structure(resolved_subject)

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

    system_content = (
        "<role>你是资深教研员与命题组长，负责规划标准试卷结构。</role>\n"
        "<requirements>\n"
        "  <rule>结构要符合高中常见题型与分值分布，保证区分度和覆盖面。</rule>\n"
        "  <rule>slot 数量控制在 3-8 个，避免过碎。</rule>\n"
        "  <rule>points_each 与 count 需合理（避免出现奇怪分值）。</rule>\n"
        "  <rule>若不确定，参考 fallback_template 微调。</rule>\n"
        "</requirements>\n"
        "<output_format>严格输出 JSON object，不要解释。</output_format>"
    )

    text = await _chat_json_with_reasoning(
        messages=[
            {"role": "system", "content": system_content},
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
        return get_default_paper_structure(resolved_subject)

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
        return get_default_paper_structure(resolved_subject)

    return {"slots": normalized_slots, "notes": [str(x).strip() for x in (obj.get("notes") or []) if str(x or "").strip()][:8]}
