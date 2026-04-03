from __future__ import annotations

import json
from typing import Optional

from backend.core.settings import LESSON_PLAN_MODEL
from backend.llm.client import is_llm_configured
from backend.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.question_library.gen_utils import ReasoningEventHandler, _clip


async def build_source_pack(
    study_markdown: str,
    subject: str,
    topic: str,
    *,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    subj = str(subject or "").strip()
    top = str(topic or "").strip()
    md = _clip(str(study_markdown or ""), 12000)

    base = {
        "subject": subj,
        "topic": top,
        "study_markdown": md,
        "facts": [],
        "skills": [],
        "common_mistakes": [],
        "forbidden_patterns": [],
        "reference_patterns": [],
        "reference_examples": [],
        "difficulty_calibration": [],
        "reference_format_conventions": [],
        "reference_question_count": 0,
        "reference_summary": "",
    }

    if not is_llm_configured() or not md.strip():
        return base

    payload = {
        "subject": subj,
        "topic": top,
        "study_markdown": md,
        "output_schema": {
            "facts": "string[] (关键事实/公式/结论)",
            "skills": "string[] (能力点/解题方法)",
            "common_mistakes": "string[] (常见误区)",
            "forbidden_patterns": "string[] (模板题/低质量套路的特征，用于避免生成)",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    "<role>你是高中教研专家，负责从学习资料中提炼直接可用于出题的结构化要素。</role>\n"
                    "<field_guidelines>\n"
                    "  <field name='facts'>核心公式/定理/结论，每条可独立成为考点，≤20条</field>\n"
                    "  <field name='skills'>能力考查点，如参数讨论、换元化简、分类讨论、反证法、数形结合、极限思想、归纳推理、构造法、待定系数、逆向思维、特殊化策略，≤20条，注重多样性</field>\n"
                    "  <field name='common_mistakes'>学生常见误区，具体可操作。≤10条</field>\n"
                    "  <field name='forbidden_patterns'>模板化/低质量套路特征。≤10条</field>\n"
                    "</field_guidelines>\n"
                    "<requirement>提炼结果要具体、可操作，避免笼统概括。</requirement>\n"
                    "<output_format>严格输出 JSON object。</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=0,
        req_id_prefix="ql_distill",
        retries=2,
        raise_on_fail=False,
        stage_id="source_pack",
        stage_label="素材整理",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )

    obj = _extract_json_obj(text)
    facts = [str(x).strip() for x in (obj.get("facts") or []) if str(x or "").strip()]
    skills = [str(x).strip() for x in (obj.get("skills") or []) if str(x or "").strip()]
    mistakes = [str(x).strip() for x in (obj.get("common_mistakes") or []) if str(x or "").strip()]
    forbidden = [str(x).strip() for x in (obj.get("forbidden_patterns") or []) if str(x or "").strip()]

    base["facts"] = facts[:24]
    base["skills"] = skills[:24]
    base["common_mistakes"] = mistakes[:24]
    base["forbidden_patterns"] = forbidden[:24]
    return base

