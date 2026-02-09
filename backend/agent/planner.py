from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import httpx

from backend.agent.config import AgentConfig
from backend.agent.types import CompressedContext, ExecutionPlan, PlanStep, UserProfile
from backend.core.settings import (
    API_TIMEOUT,
    DEFAULT_SUBJECT,
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_MAX_TOKENS,
    LESSON_PLAN_TEMPERATURE,
)


_ALLOWED_TOOLS: Dict[str, str] = {
    "split_knowledge_points": "把主题拆成多个可检索子知识点（输出 knowledge_points 列表）",
    "web_search_knowledge": "联网搜索知识点（Exa 优先，智谱兜底）",
    "wikipedia_search": "Wikipedia 百科检索（中文）",
    "search_questions_by_knowledge": "题库按知识点搜题（例题+练习题）",
    "aggregate_knowledge": "聚合：拆分 + 网搜 + 百科 + 题库",
    "generate_study_material": "生成讲解与例题解答（基于聚合结果）",
    "assemble_study_archive": "组装最终 Markdown（自学档案）",
    "revise_markdown": "按审查问题修订 Markdown（可选）",
    "save_markdown_file": "保存 Markdown 到文件",
    "review_content": "内容审查（结构/完整性/可靠性）",
    "browse_web_pages": "Browse and extract page text (best-effort)",
}


def _difficulty_from_profile(profile: UserProfile) -> str:
    score = float(profile.ability_score or 0.5)
    if score < 0.4:
        return "简单"
    if score < 0.7:
        return "中等"
    return "困难"


def _extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


class Planner:
    def __init__(self, *, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_env()

    async def _call_planner_llm(self, *, messages: List[Dict[str, str]], max_tokens: int = 1400) -> str:
        if not LESSON_PLAN_API_KEY:
            return ""

        headers = {"Authorization": f"Bearer {LESSON_PLAN_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": self.config.planner_model,
            "messages": messages,
            "temperature": float(LESSON_PLAN_TEMPERATURE or 0.4),
            "max_tokens": int(max_tokens or LESSON_PLAN_MAX_TOKENS or 1400),
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=float(API_TIMEOUT or 120)) as client:
            resp = await client.post(
                f"{LESSON_PLAN_BASE_URL.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except Exception:
            return ""

    def _fallback_plan(
        self,
        *,
        topic: str,
        subject: str,
        difficulty: str,
        iteration: int,
        issues: Optional[List[str]],
    ) -> ExecutionPlan:
        def sid(prefix: str) -> str:
            return f"{prefix}-{iteration}-{uuid.uuid4().hex[:8]}"

        steps: List[PlanStep] = [
            PlanStep(
                id=sid("split_knowledge_points"),
                title="拆分知识点",
                tool="split_knowledge_points",
                arguments={"topic": topic, "subject": subject, "min_points": 3, "max_points": 10},
                thought="先把主题拆成多个可操作的子知识点，后续逐点探索并展示进度。",
            ),
            PlanStep(
                id=sid("web_search_knowledge"),
                title="联网搜索知识点",
                tool="web_search_knowledge",
                arguments={
                    "topic": topic,
                    "subject": subject,
                    "limit": 8,
                    "text_max_length": 6000,
                    "query_hint": "定义 概念 入门",
                    "concurrency": 3,
                },
                foreach_knowledge_point=True,
                thought="为每个知识点检索权威/可用的讲解资料，补足定义与常见结论。",
            ),
            PlanStep(
                id=sid("web_search_knowledge_props"),
                title="联网搜索知识点（性质/定理/结论）",
                tool="web_search_knowledge",
                arguments={
                    "topic": topic,
                    "subject": subject,
                    "limit": 8,
                    "text_max_length": 6000,
                    "query_hint": "性质 定理 公式 结论",
                    "concurrency": 3,
                },
                foreach_knowledge_point=True,
                thought="第二轮检索：补齐性质、常用结论与关键推理线索，为讲解提供更扎实的依据。",
            ),
            PlanStep(
                id=sid("web_search_knowledge_types"),
                title="联网搜索知识点（题型/方法/易错点）",
                tool="web_search_knowledge",
                arguments={
                    "topic": topic,
                    "subject": subject,
                    "limit": 8,
                    "text_max_length": 6000,
                    "query_hint": "常见题型 解题方法 套路 易错点",
                    "concurrency": 3,
                },
                foreach_knowledge_point=True,
                thought="第三轮检索：收集常见题型、套路与易错点，保证自学材料更贴近做题场景。",
            ),
            PlanStep(
                id=sid("web_search_knowledge_proofs"),
                title="联网搜索知识点（证明/推导/为什么）",
                tool="web_search_knowledge",
                arguments={
                    "topic": topic,
                    "subject": subject,
                    "limit": 6,
                    "text_max_length": 5200,
                    "query_hint": "证明 推导 为什么",
                    "concurrency": 3,
                },
                foreach_knowledge_point=True,
                thought="第四轮检索：补齐“为什么成立”的推导/证明思路，避免讲解停留在背结论。",
            ),
            PlanStep(
                id=sid("web_search_knowledge_apps"),
                title="联网搜索知识点（应用/例子/训练）",
                tool="web_search_knowledge",
                arguments={
                    "topic": topic,
                    "subject": subject,
                    "limit": 6,
                    "text_max_length": 5200,
                    "query_hint": "应用 例子 训练",
                    "concurrency": 3,
                },
                foreach_knowledge_point=True,
                thought="第五轮检索：补齐应用场景与典型例子，让自学材料更像“能直接拿来练”。",
            ),
            PlanStep(
                id=sid("browse_web_pages"),
                title="浏览网页并提取正文（DeepResearch）",
                tool="browse_web_pages",
                arguments={"topic": topic, "subject": subject, "top_k": 3, "max_chars": 16000, "concurrency": 2},
                foreach_knowledge_point=True,
                thought="打开关键来源页面，提取更长的正文摘录，避免只靠搜索摘要导致信息不完整。",
            ),
            PlanStep(
                id=sid("wikipedia_search"),
                title="Wikipedia 百科检索",
                tool="wikipedia_search",
                arguments={
                    "topic": topic,
                    "subject": subject,
                    "lang": "zh",
                    "sentences": 6,
                    "max_content_length": 6000,
                    "concurrency": 3,
                },
                foreach_knowledge_point=True,
                thought="为每个知识点补充百科式定义与关键术语，帮助结构化讲解。",
            ),
            PlanStep(
                id=sid("search_questions_by_knowledge"),
                title="题库按知识点检索（例题+练习题）",
                tool="search_questions_by_knowledge",
                arguments={
                    "topic": topic,
                    "subject": subject,
                    "difficulty": difficulty,
                    "examples_limit": 1,
                    "exercises_limit": 6,
                    "max_pages": 3,
                },
                foreach_knowledge_point=True,
                thought="为每个知识点搜集高质量例题与练习题，作为讲解与训练材料。",
            ),
            PlanStep(
                id=sid("aggregate_knowledge"),
                title="聚合多源资料（按知识点）",
                tool="aggregate_knowledge",
                arguments={"topic": topic, "subject": subject},
                foreach_knowledge_point=True,
                thought="把百科/网搜/题库结果按知识点聚合，形成可用于写作的统一素材。",
            ),
            PlanStep(
                id=sid("generate_study_material"),
                title="生成讲解与例题解答（按知识点）",
                tool="generate_study_material",
                arguments={
                    "topic": topic,
                    "subject": subject,
                    "max_examples": 1,
                    "max_points": 1,
                    "max_web_results": 10,
                    "max_web_pages": 3,
                    "max_page_chars": 4200,
                },
                foreach_knowledge_point=True,
                thought="根据聚合素材，为当前知识点生成讲解与例题的详细步骤（作为该知识点的研究报告）。",
            ),
            PlanStep(
                id=sid("assemble_study_archive"),
                title="组装自学档案 Markdown",
                tool="assemble_study_archive",
                arguments={"topic": topic, "subject": subject},
                thought="将生成内容整理成结构化 Markdown：讲解 → 例题步骤 → 练习题。",
            ),
        ]

        if iteration > 0 and issues:
            steps.append(
                PlanStep(
                    id=sid("revise_markdown"),
                    title="根据审查问题修订 Markdown",
                    tool="revise_markdown",
                    arguments={"issues": issues},
                    thought="根据自检发现的问题修订内容，提升完整性与可读性。",
                )
            )

        steps.extend(
            [
                PlanStep(
                    id=sid("save_markdown_file"),
                    title="保存 Markdown 到文件",
                    tool="save_markdown_file",
                    arguments={"topic": topic, "dir": "study_archives"},
                    thought="把最终结果保存为本地 Markdown 文件，便于复习与分享。",
                ),
                PlanStep(
                    id=sid("review_content"),
                    title="内容审查",
                    tool="review_content",
                    arguments={"topic": topic, "subject": subject},
                    thought="对结构、准确性与练习题质量做最后自检，避免明显错误与空泛表述。",
                ),
            ]
        )

        rationale = f"计划：拆分→逐点百科/联网→逐点搜题→聚合→生成→组装→保存→审查（学科：{subject}，难度：{difficulty}）"
        return ExecutionPlan(topic=topic, steps=steps, rationale=rationale)

    def _parse_llm_plan(
        self,
        obj: Dict[str, Any],
        *,
        topic: str,
        subject: str,
        difficulty: str,
        iteration: int,
        issues: Optional[List[str]],
    ) -> Optional[ExecutionPlan]:
        steps_raw = obj.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            return None

        def sid(prefix: str) -> str:
            return f"{prefix}-{iteration}-{uuid.uuid4().hex[:8]}"

        steps: List[PlanStep] = []
        for idx, item in enumerate(steps_raw[:120]):
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool") or "").strip()
            if tool not in _ALLOWED_TOOLS:
                continue
            title = str(item.get("title") or tool).strip() or tool
            arguments = item.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            thought = str(item.get("thought") or "").strip()
            foreach_kp = bool(item.get("foreach_knowledge_point") or False)
            foreach_limit = 0
            try:
                foreach_limit = int(item.get("foreach_limit") or 0)
            except Exception:
                foreach_limit = 0
            step_id = str(item.get("id") or "").strip() or sid(f"{tool}-{idx}")

            steps.append(
                PlanStep(
                    id=step_id,
                    title=title,
                    tool=tool,
                    arguments=dict(arguments),
                    thought=thought,
                    foreach_knowledge_point=foreach_kp,
                    foreach_limit=max(0, foreach_limit),
                )
            )

        if not steps:
            return None

        # Ensure the plan starts with split_knowledge_points.
        if steps[0].tool != "split_knowledge_points":
            steps.insert(
                0,
                PlanStep(
                    id=sid("split_knowledge_points"),
                    title="拆分知识点",
                    tool="split_knowledge_points",
                    arguments={"topic": topic, "subject": subject, "min_points": 3, "max_points": 10},
                    thought="先拆分知识点，方便逐点探索并可视化进度。",
                ),
            )

        # Ensure essential finishing steps exist.
        required_tail = ["generate_study_material", "assemble_study_archive", "save_markdown_file", "review_content"]
        existing_tools = {s.tool for s in steps}
        for tool in required_tail:
            if tool in existing_tools:
                continue
            if tool == "generate_study_material":
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="生成讲解与例题解答",
                        tool=tool,
                        arguments={"topic": topic, "subject": subject, "max_examples": 1, "max_points": 8},
                        thought="生成讲解与例题步骤，形成可直接自学的内容。",
                    )
                )
            elif tool == "assemble_study_archive":
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="组装自学档案 Markdown",
                        tool=tool,
                        arguments={"topic": topic, "subject": subject},
                        thought="整理为 Markdown，自学结构更清晰。",
                    )
                )
            elif tool == "save_markdown_file":
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="保存 Markdown 到文件",
                        tool=tool,
                        arguments={"topic": topic, "dir": "study_archives"},
                        thought="保存到本地文件，方便后续复习。",
                    )
                )
            elif tool == "review_content":
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="内容审查",
                        tool=tool,
                        arguments={"topic": topic, "subject": subject},
                        thought="最后审查结构与可靠性，避免明显错误。",
                    )
                )

        rationale = str(obj.get("rationale") or "").strip()
        if not rationale:
            rationale = f"计划：自主规划（学科：{subject}，难度：{difficulty}）"

        # If reflection issues exist, allow the model to add revise step; otherwise we keep it optional.
        if iteration > 0 and issues and "revise_markdown" not in existing_tools:
            steps.append(
                PlanStep(
                    id=sid("revise_markdown"),
                    title="根据审查问题修订 Markdown",
                    tool="revise_markdown",
                    arguments={"issues": issues},
                    thought="按审查问题修订内容。",
                )
            )

        return ExecutionPlan(topic=topic, steps=steps, rationale=rationale)

    async def plan(
        self,
        *,
        topic: str,
        user_profile: UserProfile,
        context: CompressedContext,
        iteration: int = 0,
    ) -> ExecutionPlan:
        topic = (topic or "").strip()
        subject = str(user_profile.preferences.get("subject") or DEFAULT_SUBJECT).strip() or DEFAULT_SUBJECT
        difficulty = _difficulty_from_profile(user_profile)

        last_reflection = context.working_memory.get("last_reflection") or {}
        issues = last_reflection.get("issues") if isinstance(last_reflection, dict) else None

        # If planner LLM isn't configured, use a deterministic fallback plan.
        if not LESSON_PLAN_API_KEY:
            return self._fallback_plan(
                topic=topic,
                subject=subject,
                difficulty=difficulty,
                iteration=iteration,
                issues=issues if isinstance(issues, list) else None,
            )

        tool_desc = "\n".join([f"- {k}: {v}" for k, v in _ALLOWED_TOOLS.items()])
        prompt = {
            "task": topic,
            "subject": subject,
            "difficulty": difficulty,
            "ability_score": float(user_profile.ability_score or 0.5),
            "iteration": iteration,
            "reflection_issues": issues if isinstance(issues, list) else [],
            "allowed_tools": list(_ALLOWED_TOOLS.keys()),
            "notes": [
                "必须输出 JSON 对象，不要 Markdown，不要额外解释文字。",
                "计划必须以 split_knowledge_points 开始。",
                "建议对 web_search_knowledge / browse_web_pages / wikipedia_search / search_questions_by_knowledge / aggregate_knowledge / generate_study_material 使用 foreach_knowledge_point=true，便于前端显示逐知识点进度。",
                "当你使用 foreach_knowledge_point=true 时，请尽量把这些步骤连续排列（执行器会按知识点 DFS 深挖：一个知识点做完完整研究链再换下一个）。",
                "每一步请给出 thought（1-2 句，解释做这一步的目的；避免冗长推理）。",
                "steps 数量允许更长：每个知识点可 6~12 个工具调用；总 steps 可到 120（必要时）。",
                "DeepResearch建议：对每个知识点做 4~8 轮 web_search_knowledge（用 query_hint 区分：定义/性质/题型/证明/应用/易错），然后调用 browse_web_pages 提取网页正文摘录。",
            ],
            "tool_descriptions": tool_desc,
        }

        system = (
            "你是自学资料生成系统的 Planner。你要输出一个可执行的计划 JSON。\n"
            "输出 schema:\n"
            '{\n  "rationale": "string",\n  "steps": [\n'
            '    {"id": "optional", "title": "string", "tool": "string", "arguments": {}, '
            '"thought": "string", "foreach_knowledge_point": false, "foreach_limit": 0}\n'
            "  ]\n}\n"
            "严格要求：只输出 JSON。"
        )

        try:
            text = await self._call_planner_llm(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                max_tokens=1400,
            )
            obj = _extract_json_obj(text)
            parsed = self._parse_llm_plan(
                obj,
                topic=topic,
                subject=subject,
                difficulty=difficulty,
                iteration=iteration,
                issues=issues if isinstance(issues, list) else None,
            )
            if parsed is not None:
                return parsed
        except Exception:
            pass

        return self._fallback_plan(
            topic=topic,
            subject=subject,
            difficulty=difficulty,
            iteration=iteration,
            issues=issues if isinstance(issues, list) else None,
        )
