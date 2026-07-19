from __future__ import annotations

import json
from typing import List, Optional

from backend.core.settings import LESSON_PLAN_MODEL
from backend.generation.question_library.gen_common import _clip_unique
from backend.generation.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.generation.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry


def _reference_analysis_system_prompt() -> str:
    return create_default_prompt_registry().render("question.reference.analyze.v1").content


def _normalize_reference_example(item: dict) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    question_id = str(item.get("question_id") or item.get("id") or "").strip()
    stem = str(item.get("stem") or item.get("question") or "").strip()
    if not stem:
        return None
    return {
        "question_id": question_id,
        "source": str(item.get("source") or "").strip(),
        "why_selected": _clip(str(item.get("why_selected") or item.get("summary") or "").strip(), 120),
        "stem": _clip(stem, 260),
        "answer_style": _clip(str(item.get("answer_style") or item.get("answer") or "").strip(), 160),
        "analysis_style": _clip(str(item.get("analysis_style") or item.get("analysis") or "").strip(), 220),
    }


def _fallback_reference_analysis(topic: str, reference_questions: List[dict]) -> dict:
    patterns: List[str] = []
    difficulty_markers: List[str] = []
    innovative_angles: List[str] = []
    format_conventions: List[str] = []
    examples: List[dict] = []
    topic_text = str(topic or "").strip()
    for question in reference_questions[:5]:
        if not isinstance(question, dict):
            continue
        question_type = str(question.get("question_type") or "").strip()
        knowledge = str(question.get("knowledge_points") or topic_text or "").strip()
        difficulty = str(question.get("difficulty") or "").strip()
        source = str(question.get("source") or "").strip()
        if question_type or knowledge:
            patterns.append(f"围绕{knowledge or topic_text}设计{question_type or '综合'}设问，保持题干结构紧凑。")
        if difficulty:
            difficulty_markers.append(f"参考题整体难度以{difficulty}为主；只借鉴课内知识边界与认知负荷，不把长推导本身当作优点。")
        if source:
            innovative_angles.append(f"可借鉴{source}中的设问切入角度，但需替换具体数值、情境与结论。")
        if question.get("answer") or question.get("analysis"):
            format_conventions.append("答案先给关键结论，再用最短充分证据解释决定性结构。")
        normalized_example = _normalize_reference_example(
            {
                "question_id": question.get("question_id"),
                "source": source,
                "why_selected": f"覆盖{knowledge or topic_text}的常见设问方式",
                "stem": question.get("stem"),
                "answer": question.get("answer"),
                "analysis": question.get("analysis"),
            }
        )
        if normalized_example is not None:
            examples.append(normalized_example)
    patterns = _clip_unique(
        patterns
        + [
            f"围绕{topic_text or '目标知识点'}提取可先预测、再验证的决定性结构线索。",
            "优先识别典型表征、不变量、边界变化和容易产生的错误直觉。",
            "避免直接套用教材例题表达，保持真题风格但不复刻原题。",
        ],
        6,
    )
    difficulty_markers = _clip_unique(
        difficulty_markers
        + [
            "难度标定同时考虑知识边界、表征转换、推理负荷和运算量，避免用步骤长度替代难度。",
            "自主练习应保持低入口，用一个决定性观察和短验证形成可迁移的内部模型。",
        ],
        6,
    )
    innovative_angles = _clip_unique(
        innovative_angles
        + [
            "Extract reusable question order, condition combinations, and answer organization from real papers.",
            "允许在真题常考方向上做新的条件组合与场景迁移。",
        ],
        6,
    )
    format_conventions = _clip_unique(
        format_conventions
        + [
            "答案表述保持结论清晰，解析按关键步骤推进，不写多余点评。",
            "若有多阶段，解析需对应第一感觉、结构解释、最小检验和迁移任务。",
        ],
        6,
    )
    examples = [example for example in examples if isinstance(example, dict)][:3]
    while len(examples) < 2 and reference_questions:
        question = reference_questions[len(examples) % len(reference_questions)]
        normalized_example = _normalize_reference_example(
            {
                "question_id": question.get("question_id"),
                "source": question.get("source"),
                "why_selected": f"补充{topic_text or '目标知识点'}的代表性问法",
                "stem": question.get("stem"),
                "answer": question.get("answer"),
                "analysis": question.get("analysis"),
            }
        )
        if normalized_example is None:
            break
        examples.append(normalized_example)
    return {
        "question_patterns": patterns[:6],
        "difficulty_markers": difficulty_markers[:6],
        "innovative_angles": innovative_angles[:6],
        "format_conventions": format_conventions[:6],
        "representative_examples": examples[:3],
    }


async def analyze_reference_questions(
    *,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    reference_questions: List[dict],
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    fallback = _fallback_reference_analysis(topic, reference_questions)
    if not is_llm_configured() or not reference_questions:
        return fallback

    payload = {
        "subject": str(subject or "").strip(),
        "topic": str(topic or "").strip(),
        "difficulty": str(difficulty or "").strip(),
        "question_type": str(question_type or "").strip(),
        "reference_questions": [
            {
                "question_id": str((item or {}).get("question_id") or "").strip(),
                "source": str((item or {}).get("source") or "").strip(),
                "difficulty": str((item or {}).get("difficulty") or "").strip(),
                "question_type": str((item or {}).get("question_type") or "").strip(),
                "knowledge_points": str((item or {}).get("knowledge_points") or "").strip(),
                "stem": _clip(str((item or {}).get("stem") or "").strip(), 260),
                "answer": _clip(str((item or {}).get("answer") or "").strip(), 160),
                "analysis": _clip(str((item or {}).get("analysis") or "").strip(), 240),
            }
            for item in (reference_questions or [])[:8]
            if isinstance(item, dict)
        ],
        "output_schema": {
            "question_patterns": "string[]",
            "difficulty_markers": "string[]",
            "innovative_angles": "string[]",
            "format_conventions": "string[]",
            "representative_examples": [
                {
                    "question_id": "string",
                    "source": "string",
                    "why_selected": "string",
                    "stem": "string",
                    "answer_style": "string",
                    "analysis_style": "string",
                }
            ],
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    _reference_analysis_system_prompt()
                    + "\n\n"
                    "<purpose>References serve student intuition practice, not imitation of exam difficulty.</purpose>\n"
                    "<extract>Extract only curriculum boundaries, decisive structural cues, useful representations, invariants/boundaries, and common false intuitions.</extract>\n"
                    "<avoid>Do not praise long derivations, parameter case counts, large computation, or finale-question difficulty as quality by themselves.</avoid>\n"
                    "<transfer>Describe how to preserve the underlying structure while changing at least two surface features.</transfer>\n"
                    "<anti_copy>Never copy the reference stem, values, context, conclusion, or solution wording.</anti_copy>\n"
                    "<output_format>Output one strict JSON object matching output_schema.</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=0,
        req_id_prefix="ql_ref_analysis",
        retries=2,
        raise_on_fail=False,
        stage_id="reference_analysis",
        stage_label="参考题分析",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    patterns = _clip_unique(
        [str(item or "").strip() for item in (obj.get("question_patterns") or []) if str(item or "").strip()]
        + list(fallback.get("question_patterns") or []),  6,
    )
    difficulty_markers = _clip_unique(
        [str(item or "").strip() for item in (obj.get("difficulty_markers") or []) if str(item or "").strip()]
        + list(fallback.get("difficulty_markers") or []), 6,
    )
    innovative_angles = _clip_unique(
        [str(item or "").strip() for item in (obj.get("innovative_angles") or []) if str(item or "").strip()]
        + list(fallback.get("innovative_angles") or []),  6,
    )
    format_conventions = _clip_unique(
        [str(item or "").strip() for item in (obj.get("format_conventions") or []) if str(item or "").strip()]
        + list(fallback.get("format_conventions") or []), 6,
    )
    examples: List[dict] = []
    for item in (obj.get("representative_examples") or []):
        normalized = _normalize_reference_example(item if isinstance(item, dict) else {})
        if normalized is not None:
            examples.append(normalized)
    for item in fallback.get("representative_examples") or []:
        normalized = _normalize_reference_example(item if isinstance(item, dict) else {})
        if normalized is not None:
            examples.append(normalized)
    deduped_examples: List[dict] = []
    seen_example_keys: set[str] = set()
    for example in examples:
        key = json.dumps({"question_id": example.get("question_id"), "stem": example.get("stem")}, ensure_ascii=False, sort_keys=True)
        if key in seen_example_keys:
            continue
        seen_example_keys.add(key)
        deduped_examples.append(example)
        if len(deduped_examples) >= 3:
            break
    return {
        "question_patterns": patterns[:6],
        "difficulty_markers": difficulty_markers[:6],
        "innovative_angles": innovative_angles[:6],
        "format_conventions": format_conventions[:6],
        "representative_examples": deduped_examples[:3],
    }


def enrich_source_pack_with_reference(source_pack: dict, reference_analysis: dict, reference_questions: List[dict]) -> dict:
    base = dict(source_pack or {})
    analysis = reference_analysis if isinstance(reference_analysis, dict) else {}
    examples = []
    for item in analysis.get("representative_examples") or []:
        normalized = _normalize_reference_example(item if isinstance(item, dict) else {})
        if normalized is not None:
            examples.append(normalized)
    if not examples:
        for item in (reference_questions or [])[:3]:
            normalized = _normalize_reference_example(
                {
                    "question_id": str((item or {}).get("question_id") or "").strip(),
                    "source": str((item or {}).get("source") or "").strip(),
                    "why_selected": f"覆盖{str((item or {}).get('knowledge_points') or (base or {}).get('topic') or '').strip() or '目标知识点'}的代表性设问",
                    "stem": str((item or {}).get("stem") or "").strip(),
                    "answer": str((item or {}).get("answer") or "").strip(),
                    "analysis": str((item or {}).get("analysis") or "").strip(),
                }
            )
            if normalized is None:
                break
            examples.append(normalized)
    base["reference_patterns"] = _clip_unique(
        [str(item or "").strip() for item in (analysis.get("question_patterns") or []) if str(item or "").strip()]
        + [str(item or "").strip() for item in (analysis.get("innovative_angles") or []) if str(item or "").strip()],
        8,
    )
    base["reference_examples"] = examples[:3]
    base["difficulty_calibration"] = _clip_unique(
        [str(item or "").strip() for item in (analysis.get("difficulty_markers") or []) if str(item or "").strip()],
        6,
    )
    base["reference_format_conventions"] = _clip_unique(
        [str(item or "").strip() for item in (analysis.get("format_conventions") or []) if str(item or "").strip()],
        6,
    )
    base["reference_question_count"] = len([item for item in (reference_questions or []) if isinstance(item, dict)])
    base["reference_summary"] = "；".join((base.get("reference_patterns") or [])[:3])
    return base
