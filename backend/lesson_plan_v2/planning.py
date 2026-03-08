from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from backend.core.settings import LESSON_PLAN_MODEL
from backend.lesson_plan_v2.common import clean_points, extract_json_obj
from backend.lesson_plan_v2.llm import call_llm_text


async def split_knowledge_points(topic: str, subject: str, *, min_points: int = 3, max_points: int = 8) -> List[str]:
    model = str(os.getenv("LESSON_PLAN_SPLIT_MODEL") or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

    prompt = {
        "topic": topic,
        "subject": subject,
        "requirements": [
            "请把 topic 拆分为若干个可用于教学的子知识点（短语级关键词）。",
            f"数量要求：{min_points}~{max_points} 个，尽量覆盖该主题的核心内容。",
            "粒度要求：每个知识点应具体到可独立讲解的程度，避免过于宽泛（如单独的「概念」「性质」「应用」）。",
            "去重要求：合并语义相近或重复的知识点，确保列表中无冗余项。",
            "排序要求：按照教学逻辑顺序排列，从基础概念到进阶应用。",
            "命名要求：每个知识点用简洁的短语表达（5~20字），便于后续生成教研素材。",
            '输出格式：只输出严格 JSON，格式为 {"knowledge_points": ["知识点1", "知识点2", ...]}',
            "注意：不要输出 Markdown 代码块，不要添加任何解释性文字。",
        ],
    }

    last_err = ""
    for _ in range(3):
        text = await call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的学科老师，输出必须是JSON。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.2,
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
    model = str(os.getenv("LESSON_PLAN_RESEARCH_MODEL") or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

    prompt = {
        "knowledge_point": kp,
        "subject": subject,
        "topic": topic,
        "requirements": [
            "请针对该知识点进行深度教研分析，输出严格 JSON（不要 Markdown 代码块，不要解释性文字）。",
            "teaching_points（教学要点）：列出 3~6 个核心教学要点，每条应具体说明『教什么』和『怎么教』，避免泛泛而谈。",
            "common_misconceptions（常见误区）：列出 2~4 个学生容易出现的错误理解或典型错误，并简要说明正确认知。",
            "suggested_activities（建议活动）：列出 2~4 个可在课堂实施的教学活动，包括活动形式、时长建议、预期效果。",
            "key_examples（关键例题/案例）：列出 2~4 个典型例题或生活案例，要求具体、可直接用于课堂讲解或练习。",
            "所有字段均为字符串数组，每条内容应详实、可操作，便于直接融入教案设计。",
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
                {"role": "system", "content": "你是资深教研员，输出必须是JSON。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.3,
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
            os.getenv("LESSON_PLAN_KP_REVIEW_MODEL") or os.getenv("LESSON_PLAN_SPLIT_MODEL") or LESSON_PLAN_MODEL
        ).strip()
        or LESSON_PLAN_MODEL
    )

    prompt = {
        "topic": topic,
        "subject": subject,
        "knowledge_points": points,
        "requirements": [
            "请审核并微调上述知识点列表，使其更适合『逐点生成教研素材 + 组装成教案』。",
            f"数量要求：{min_points}~{max_points} 个；尽量不超过 {max_points} 个。",
            "去重：合并重复/同义项；避免过泛。",
            "补全：如明显缺失关键子主题，可补充 1~3 个，但不要发散到无关内容。",
            '只输出严格 JSON：{"knowledge_points": [...], "note": "..."}（不要 Markdown，不要多余文字）。',
        ],
    }

    last_err = ""
    for _ in range(3):
        text = await call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的教研员，输出必须是JSON。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.2,
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
