from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from backend.core.settings import LESSON_PLAN_MODEL, LESSON_PLAN_TEMPERATURE
from backend.generation.lesson_plan.common import extract_json_obj, lesson_plan_infinite_max_tokens
from backend.generation.lesson_plan.llm import call_llm_text
from backend.generation.lesson_plan.prompts import get_system_prompt


async def generate_lesson_plan_json(
    *,
    subject: str,
    grade: str,
    topic: str,
    duration_minutes: int,
    objectives: Optional[List[str]],
    teaching_style: Optional[str],
    student_level: Optional[str],
    additional_requirements: Optional[str],
    knowledge_points: List[str],
    research_context: List[Dict[str, Any]],
) -> Dict[str, Any]:
    model = str(os.getenv("LESSON_PLAN_WRITER_MODEL") or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

    prompt_parts = [
        f"Write a {int(duration_minutes)}-minute lesson plan for the following course as structured JSON:",
        f"- 学科：{subject}",
        f"- 年级：{grade}",
        f"- 课题：{topic}",
        f"- 知识点拆分：{', '.join([kp for kp in knowledge_points if str(kp).strip()])}",
    ]
    if objectives:
        cleaned = [str(x) for x in (objectives or []) if str(x).strip()]
        if cleaned:
            prompt_parts.append(f"- 教学目标（用户提供）：{', '.join(cleaned)}")
    if teaching_style:
        prompt_parts.append(f"- 教学风格：{teaching_style}")
    if student_level:
        prompt_parts.append(f"- 学生水平：{student_level}")
    if additional_requirements:
        prompt_parts.append(f"- 额外要求：{additional_requirements}")

    if research_context:
        prompt_parts.append("")
        prompt_parts.append("Below are curriculum-research notes for each knowledge point. Use them only as reference and reorganize in your own words:")
        prompt_parts.append(json.dumps(research_context, ensure_ascii=False, indent=2))

    prompt_parts.append("")
    prompt_parts.append("Output requirements: output strict JSON only. Do not output Markdown code fences or extra explanation.")
    prompt_parts.append("JSON must contain: title, objectives, sections, summary.")
    prompt_parts.append(
        "Each sections item must contain: title, duration_minutes(number), content, activities(string[]), resources(string[])."
    )

    last_err = ""
    for _ in range(3):
        text = await call_llm_text(
            messages=[
                {"role": "system", "content": get_system_prompt()},
                {"role": "user", "content": "\n".join(prompt_parts)},
            ],
            model=model,
            temperature=float(LESSON_PLAN_TEMPERATURE or 0.6),
            max_tokens=lesson_plan_infinite_max_tokens(),
            raise_on_fail=True,
        )
        obj = extract_json_obj(text)
        if obj.get("title") and isinstance(obj.get("sections"), list):
            obj.pop("references", None)
            return obj
        last_err = "invalid_json"

    raise RuntimeError(f"llm_generate_failed: {last_err or 'unknown'} model={model}")


def lesson_plan_to_markdown(
    plan: Dict[str, Any],
    *,
    subject: str,
    grade: str,
    topic: str,
    duration_minutes: int,
    knowledge_points: List[str],
) -> str:
    title = str(plan.get("title") or topic or "教案").strip() or "教案"

    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- 学科：{subject or '（未填写）'}")
    lines.append(f"- 年级：{grade or '（未填写）'}")
    lines.append(f"- 课题：{topic or title}")
    lines.append(f"- 课时：{int(duration_minutes)} 分钟")
    if knowledge_points:
        kp_txt = "、".join([kp for kp in knowledge_points if str(kp).strip()])
        if kp_txt:
            lines.append(f"- 知识点：{kp_txt}")
    lines.append("")

    lines.append("## 教学目标")
    lines.append("")
    objectives = plan.get("objectives")
    if isinstance(objectives, list) and objectives:
        for obj in objectives[:12]:
            if not isinstance(obj, dict):
                continue
            desc = str(obj.get("description") or "").strip()
            if desc:
                lines.append(f"- {desc}")
    else:
        lines.append("- （未生成教学目标）")
    lines.append("")

    lines.append("## 教学过程")
    lines.append("")
    sections = plan.get("sections")
    if isinstance(sections, list) and sections:
        for sec in sections[:20]:
            if not isinstance(sec, dict):
                continue
            st = str(sec.get("title") or "").strip() or "教学环节"
            dm = sec.get("duration_minutes")
            try:
                dm_i = int(dm)
            except (TypeError, ValueError):
                dm_i = 0
            lines.append(f"### {st}{f'（{dm_i}分钟）' if dm_i else ''}")
            lines.append("")

            content = str(sec.get("content") or "").strip()
            if content:
                lines.append(content)
                lines.append("")

            acts = sec.get("activities")
            if isinstance(acts, list) and any(str(x or "").strip() for x in acts):
                lines.append("活动：")
                for a in acts[:12]:
                    s = str(a or "").strip()
                    if s:
                        lines.append(f"- {s}")
                lines.append("")

            res = sec.get("resources")
            if isinstance(res, list) and any(str(x or "").strip() for x in res):
                lines.append("资源：")
                for r in res[:12]:
                    s = str(r or "").strip()
                    if s:
                        lines.append(f"- {s}")
                lines.append("")
    else:
        lines.append("（未生成教学过程）")
        lines.append("")

    summary = str(plan.get("summary") or "").strip()
    if summary:
        lines.append("## 小结")
        lines.append("")
        lines.append(summary)
        lines.append("")

    return "\n".join(lines).strip() + "\n"
