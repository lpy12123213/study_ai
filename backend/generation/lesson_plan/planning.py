from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from backend.core.settings import LESSON_PLAN_MODEL, SUB_MODEL
from backend.generation.lesson_plan.common import clean_points, extract_json_obj
from backend.generation.lesson_plan.llm import call_llm_text
from backend.llm.prompts import create_default_prompt_registry


def _prompt(prompt_id: str) -> str:
    return create_default_prompt_registry().render(prompt_id).content


async def split_knowledge_points(topic: str, subject: str, *, min_points: int = 3, max_points: int = 8) -> List[str]:
    model = str(os.getenv("LESSON_PLAN_SPLIT_MODEL") or SUB_MODEL or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

    prompt = {
        "topic": topic,
        "subject": subject,
        "requirements": [
            "Split topic into several teachable sub-knowledge points as phrase-level keywords.",
            f"数量要求：{min_points}~{max_points} 个，尽量覆盖该主题的核心内容。",
            "粒度要求：每个知识点应具体到可独立讲解的程度，避免过于宽泛（如单独的「概念」「性质」「应用」）。",
            "去重要求：合并语义相近或重复的知识点，确保列表中无冗余项。",
            "排序要求：按照教学逻辑顺序排列，从基础概念到进阶应用。",
            "Naming requirement: each knowledge point must be a concise phrase, suitable for later curriculum-material generation.",
            'Output format: strict JSON only, in the format {"knowledge_points": ["point1", "point2", ...]}',
            "Do not output Markdown code fences or explanatory text.",
        ],
    }

    last_err = ""
    for _ in range(3):
        text = await call_llm_text(
            messages=[
                {"role": "system", "content": _prompt("study.kp.split.v1")},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.6,
            max_tokens=2400,
            raise_on_fail=True,
        )
        obj = extract_json_obj(text)
        points = clean_points(list(obj.get("knowledge_points") or []), max_points=max_points)
        if len(points) >= min_points:
            return points[:max_points]
        last_err = f"too_few_points got={len(points)} min={min_points}"

    raise RuntimeError(f"llm_split_failed: {last_err or 'unknown'} model={model}")


async def research_knowledge_point(kp: str, subject: str, topic: str) -> Dict[str, Any]:
    model = str(os.getenv("LESSON_PLAN_RESEARCH_MODEL") or SUB_MODEL or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

    prompt = {
        "knowledge_point": kp,
        "subject": subject,
        "topic": topic,
        "requirements": [
            "Perform in-depth instructional analysis for this knowledge point and output strict JSON. Do not output Markdown code fences or explanatory text.",
            "teaching_points（教学要点）：列出 3~6 个核心教学要点，每条应具体说明『教什么』和『怎么教』，避免泛泛而谈。",
            "common_misconceptions（常见误区）：列出 2~4 个学生容易出现的错误理解或典型错误，并简要说明正确认知。",
            "suggested_activities（建议活动）：列出 2~4 个可在课堂实施的教学活动，包括活动形式、时长建议、预期效果。",
            "key_examples（关键例题/案例）：列出 2~4 个典型例题或生活案例，要求具体、可直接用于课堂讲解或练习。",
            "All fields must be string arrays. Each item should be detailed and actionable so it can be directly integrated into lesson-plan design.",
        ],
        "output_schema": {
            "teaching_points": ["string"],
            "common_misconceptions": ["string"],
            "suggested_activities": ["string"],
            "key_examples": ["string"],
        },
    }

    last_err = ""
    for _ in range(2):
        text = await call_llm_text(
            messages=[
                {"role": "system", "content": _prompt("lesson_plan.kp_facts.v1")},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.7,
            max_tokens=2600,
            raise_on_fail=True,
        )
        obj = extract_json_obj(text)
        if obj:
            return {"knowledge_point": kp, "research": obj}
        last_err = "invalid_json"

    raise RuntimeError(f"llm_research_failed: {last_err or 'unknown'} model={model}")


async def review_knowledge_points(
    topic: str,
    subject: str,
    points: List[str],
    *,
    min_points: int,
    max_points: int,
) -> List[str]:
    model = (
        str(
            os.getenv("LESSON_PLAN_KP_REVIEW_MODEL")
            or os.getenv("LESSON_PLAN_SPLIT_MODEL")
            or SUB_MODEL
            or LESSON_PLAN_MODEL
        ).strip()
        or LESSON_PLAN_MODEL
    )

    prompt = {
        "topic": topic,
        "subject": subject,
        "knowledge_points": points,
        "requirements": [
            "Review and minimally adjust the knowledge-point list so it works better for point-by-point curriculum-material generation and lesson-plan assembly.",
            f"数量要求：{min_points}~{max_points} 个；尽量不超过 {max_points} 个。",
            "去重：合并重复/同义项；避免过泛。",
            "Completion: if key subtopics are clearly missing, add 1-3 items, but do not drift into unrelated content.",
            'Output strict JSON only: {"knowledge_points": [...], "note": "..."}. Do not output Markdown or extra text.',
        ],
    }

    last_err = ""
    for _ in range(3):
        text = await call_llm_text(
            messages=[
                {"role": "system", "content": _prompt("study.kp.review.v1")},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.6,
            max_tokens=2400,
            raise_on_fail=True,
        )
        obj = extract_json_obj(text)
        revised = obj.get("knowledge_points")
        if isinstance(revised, list):
            cleaned = clean_points(list(revised), max_points=max_points)
            if len(cleaned) >= min_points:
                return cleaned[:max_points]
            last_err = f"too_few_points got={len(cleaned)} min={min_points}"
        else:
            last_err = "invalid_json"

    raise RuntimeError(f"llm_review_failed: {last_err or 'unknown'} model={model}")
