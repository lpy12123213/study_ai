"""Lesson Plan Agent V2 - AI-powered lesson plan generation with streaming.

Flow:
1. Plan phase: split knowledge points for the topic
2. SubAgent phase: for each knowledge point, research + generate content
3. Assemble: combine into final lesson plan with references
"""

from __future__ import annotations

import json
import asyncio
import re
from typing import AsyncIterator, Optional, List, Dict, Any

from backend.core.settings import (
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_MAX_TOKENS,
    LESSON_PLAN_MODEL,
    LESSON_PLAN_TEMPERATURE,
)

SYSTEM_PROMPT = """你是一位资深教育内容设计专家，擅长编写教案。

核心原则：
1. 所有内容必须用自己的话重新组织和表达，严禁照搬任何来源的原文
2. 可以参考搜索到的资料获取事实和灵感，但必须经过消化吸收后重新撰写
3. 引用的事实需要在文末以"参考文献"形式标注来源
4. 教案应当清晰、实用、以学生为中心

输出要求：
- 输出结构化 JSON，包含以下字段：
  - title: 课程标题
  - objectives: 教学目标数组，每项含 description 和 type (knowledge/skill/attitude)
  - sections: 教学环节数组，每项含 title, duration_minutes, content, activities, resources
  - summary: 课程小结
  - references: 参考文献数组，每项含 title 和 url（若有）
- content 字段中的文字必须是你自己撰写的，不得复制粘贴来源原文
- 如需引用具体数据或结论，用脚注标记如 [1]，并在 references 中列出"""


async def _call_llm(messages: List[Dict[str, str]], *, model: str = "", temperature: float = 0.3, max_tokens: int = 4000) -> str:
    """Call OpenAI-compatible LLM and return text response."""
    import httpx

    headers = {
        "Authorization": f"Bearer {LESSON_PLAN_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or LESSON_PLAN_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{LESSON_PLAN_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        return (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()


async def _split_knowledge_points(
    topic: str, subject: str, *, min_points: int = 3, max_points: int = 8
) -> List[str]:
    """Split topic into sub-knowledge points using LLM or heuristics."""
    if LESSON_PLAN_API_KEY:
        prompt = json.dumps({
            "topic": topic,
            "subject": subject,
            "instructions": (
                "请把 topic 拆分为若干个可用于教学的子知识点（短语级关键词）。\n"
                f"- 数量：{min_points} 到 {max_points} 个\n"
                "- 每个子知识点尽量具体、互不重复\n"
                "- 仅输出严格 JSON\n"
                '- JSON 格式：{"knowledge_points": ["...", "..."]}\n'
            ),
        }, ensure_ascii=False)
        text = await _call_llm(
            messages=[
                {"role": "system", "content": "你是严谨的学科老师，输出必须是JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=600,
        )
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                obj = json.loads(text[start:end])
                points = [str(x).strip() for x in (obj.get("knowledge_points") or []) if str(x).strip()]
                if len(points) >= min_points:
                    return points[:max_points]
        except (json.JSONDecodeError, ValueError):
            pass

    # Heuristic fallback
    raw = re.split(r"[\n,，;；、/|]+", topic)
    points = [x.strip() for x in raw if x.strip()]
    if len(points) < min_points and topic.strip():
        points = [
            f"{topic} 基本概念与定义",
            f"{topic} 核心性质与定理",
            f"{topic} 典型例题与方法",
            f"{topic} 易错点与注意事项",
        ]
    return points[:max_points]


async def _research_knowledge_point(kp: str, subject: str, topic: str) -> Dict[str, Any]:
    """Research a single knowledge point: gather context for lesson plan writing."""
    result: Dict[str, Any] = {"knowledge_point": kp, "sources": []}

    if not LESSON_PLAN_API_KEY:
        return result

    # Use LLM to generate a research summary for this knowledge point
    prompt = (
        f"请为教案编写收集关于「{kp}」的教学要点（学科：{subject}，主题：{topic}）。\n\n"
        "请输出 JSON：\n"
        '{"teaching_points": ["要点1", "要点2", ...], '
        '"common_misconceptions": ["误区1", ...], '
        '"suggested_activities": ["活动1", ...], '
        '"key_examples": ["例子1", ...]}\n\n'
        "仅输出 JSON，不要额外文字。"
    )
    text = await _call_llm(
        messages=[
            {"role": "system", "content": "你是资深教研员，输出必须是JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=800,
    )
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            obj = json.loads(text[start:end])
            result["research"] = obj
    except (json.JSONDecodeError, ValueError):
        pass

    return result


async def generate_lesson_plan_stream(
    subject: str,
    grade: str,
    topic: str,
    duration_minutes: int = 45,
    objectives: Optional[List[str]] = None,
    teaching_style: Optional[str] = None,
    student_level: Optional[str] = None,
    additional_requirements: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Generate a lesson plan using AI with streaming events.

    New flow:
    1. Plan phase: split_knowledge_points
    2. SubAgent phase: research each knowledge point (parallel-ish)
    3. Generate: assemble final lesson plan with original writing + references
    """
    try:
        # ── Phase 1: Plan ─────────────────────────────────────────────
        yield {
            "event": "thinking",
            "data": {"content": f"分析教学需求：{subject} {grade}《{topic}》…"}
        }
        await asyncio.sleep(0.05)

        yield {
            "event": "tool_call",
            "data": {"name": "split_knowledge_points", "arguments": {"topic": topic, "subject": subject}}
        }

        knowledge_points = await _split_knowledge_points(topic, subject)

        yield {
            "event": "tool_result",
            "data": {
                "name": "split_knowledge_points",
                "success": True,
                "output": {"knowledge_points": knowledge_points},
            }
        }
        yield {
            "event": "thinking",
            "data": {"content": f"已拆分为 {len(knowledge_points)} 个知识点：{', '.join(knowledge_points)}"}
        }
        await asyncio.sleep(0.05)

        # ── Phase 2: SubAgent research per knowledge point ────────────
        research_results: List[Dict[str, Any]] = []

        for i, kp in enumerate(knowledge_points):
            yield {
                "event": "subagent_start",
                "data": {
                    "knowledge_point": kp,
                    "index": i,
                    "total": len(knowledge_points),
                    "content": f"SubAgent 启动：研究知识点「{kp}」",
                }
            }

            yield {
                "event": "tool_call",
                "data": {"name": "research_knowledge_point", "arguments": {"knowledge_point": kp}}
            }

            res = await _research_knowledge_point(kp, subject, topic)
            research_results.append(res)

            yield {
                "event": "tool_result",
                "data": {
                    "name": "research_knowledge_point",
                    "success": True,
                    "output": {"knowledge_point": kp, "has_research": bool(res.get("research"))},
                }
            }

            yield {
                "event": "subagent_end",
                "data": {
                    "knowledge_point": kp,
                    "index": i,
                    "total": len(knowledge_points),
                    "content": f"SubAgent 完成：「{kp}」资料收集完毕",
                }
            }
            await asyncio.sleep(0.05)

        # ── Phase 3: Generate lesson plan ─────────────────────────────
        yield {
            "event": "thinking",
            "data": {"content": "根据收集的资料，撰写教案正文（原创撰写，非照搬）…"}
        }
        await asyncio.sleep(0.05)

        if not LESSON_PLAN_API_KEY:
            plan = _create_sample_lesson_plan(
                subject, grade, topic, duration_minutes, objectives, knowledge_points
            )
            for section in plan["sections"]:
                yield {
                    "event": "content",
                    "data": {"content": section["content"], "section": section["title"]}
                }
                await asyncio.sleep(0.05)
            yield {"event": "done", "data": {"plan": plan}}
            return

        # Build rich context for the writer LLM
        research_context = []
        for r in research_results:
            kp = r.get("knowledge_point", "")
            research = r.get("research", {})
            if research:
                research_context.append({
                    "knowledge_point": kp,
                    "teaching_points": research.get("teaching_points", []),
                    "common_misconceptions": research.get("common_misconceptions", []),
                    "suggested_activities": research.get("suggested_activities", []),
                    "key_examples": research.get("key_examples", []),
                })

        prompt_parts = [
            f"请为以下课程编写一份 {duration_minutes} 分钟的教案：",
            f"- 学科：{subject}",
            f"- 年级：{grade}",
            f"- 课题：{topic}",
            f"- 知识点拆分：{', '.join(knowledge_points)}",
        ]
        if objectives:
            prompt_parts.append(f"- 教学目标：{', '.join(objectives)}")
        if teaching_style:
            prompt_parts.append(f"- 教学风格：{teaching_style}")
        if student_level:
            prompt_parts.append(f"- 学生水平：{student_level}")
        if additional_requirements:
            prompt_parts.append(f"- 额外要求：{additional_requirements}")

        if research_context:
            prompt_parts.append("\n以下是各知识点的教研资料（仅供参考，请用自己的话重新组织）：")
            prompt_parts.append(json.dumps(research_context, ensure_ascii=False, indent=2))

        prompt_parts.extend([
            "",
            "重要写作要求：",
            "1. 所有教案内容必须用你自己的话撰写，严禁照搬任何来源的原文",
            "2. 参考资料仅用于获取事实和灵感，必须经过消化吸收后重新表达",
            "3. 在文末 references 数组中列出你参考的来源（标题+URL，若有）",
            "4. 如在正文中引用具体数据或结论，用 [1] [2] 等脚注标记",
            "5. 教案应覆盖所有拆分出的知识点",
            "",
            "请输出严格 JSON（不要 Markdown 代码块）。",
        ])

        user_prompt = "\n".join(prompt_parts)

        # Stream the generation
        import httpx

        headers = {
            "Authorization": f"Bearer {LESSON_PLAN_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": LESSON_PLAN_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": LESSON_PLAN_TEMPERATURE,
            "max_tokens": LESSON_PLAN_MAX_TOKENS,
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{LESSON_PLAN_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code != 200:
                    yield {"event": "error", "data": {"message": f"API error: {response.status_code}"}}
                    return

                content_buffer = ""
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            content_buffer += content
                            yield {"event": "content", "data": {"content": content, "section": "generation"}}
                    except json.JSONDecodeError:
                        continue

                # Parse final JSON
                try:
                    json_start = content_buffer.find("{")
                    json_end = content_buffer.rfind("}") + 1
                    if json_start >= 0 and json_end > json_start:
                        plan = json.loads(content_buffer[json_start:json_end])
                        # Ensure references field exists
                        if "references" not in plan:
                            plan["references"] = []
                        yield {"event": "done", "data": {"plan": plan}}
                    else:
                        yield {"event": "done", "data": {"plan": {"content": content_buffer, "references": []}}}
                except json.JSONDecodeError:
                    yield {"event": "done", "data": {"plan": {"content": content_buffer, "references": []}}}

    except Exception as e:
        yield {"event": "error", "data": {"message": str(e)}}


def _create_sample_lesson_plan(
    subject: str,
    grade: str,
    topic: str,
    duration_minutes: int,
    objectives: Optional[List[str]] = None,
    knowledge_points: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a sample lesson plan structure (fallback when no API key)."""
    intro_time = max(5, duration_minutes // 6)
    main_time = duration_minutes - intro_time - 10
    conclusion_time = 10

    kp_text = ""
    if knowledge_points:
        kp_text = "本节课涵盖以下知识点：" + "、".join(knowledge_points) + "。"

    return {
        "title": f"{topic}",
        "subject": subject,
        "grade": grade,
        "topic": topic,
        "duration_minutes": duration_minutes,
        "objectives": [
            {"description": obj, "type": "knowledge"}
            for obj in (objectives or [f"理解{topic}的核心概念"])
        ],
        "sections": [
            {
                "title": "导入",
                "duration_minutes": intro_time,
                "content": f"以与{topic}相关的情境引入，激发学生兴趣。{kp_text}回顾前置知识，预告学习目标。",
                "activities": ["情境导入", "学习目标展示"],
                "resources": ["多媒体课件"],
            },
            {
                "title": "新授",
                "duration_minutes": main_time,
                "content": f"围绕{topic}的核心概念展开讲解，结合互动环节加深理解。",
                "activities": ["讲授新知", "引导探究", "小组讨论"],
                "resources": ["教材", "练习单", "多媒体资源"],
            },
            {
                "title": "总结与评价",
                "duration_minutes": conclusion_time,
                "content": "梳理本节要点，检测学习效果，布置课后任务。",
                "activities": ["课堂小测", "要点回顾", "作业布置"],
                "resources": ["检测卡"],
            },
        ],
        "summary": f"本节课用 {duration_minutes} 分钟完成{grade}{subject}《{topic}》的教学。",
        "references": [],
    }
