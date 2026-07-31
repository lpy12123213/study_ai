from __future__ import annotations

import json

from backend.core.settings import LESSON_PLAN_MODEL
from backend.generation.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.generation.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry


def _source_pack_system_prompt() -> str:
    return create_default_prompt_registry().render("question.source_pack.extract.v1").content


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
        "curriculum_standard": "",
        "question_requirements": [],
        "core_competencies": [],
        "knowledge_scope": {"in_scope": [], "out_of_scope": []},
        "prerequisites": [],
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
            "forbidden_patterns": "string[] (features of template-like or low-quality routines to avoid during generation)",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": _source_pack_system_prompt(),
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
