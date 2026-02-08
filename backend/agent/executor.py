from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.agent.config import AgentConfig
from backend.agent.types import CompressedContext, PlanStep, StepResult
from backend.crawler_manager import get_crawler
from backend.core.settings import (
    API_TIMEOUT,
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_MAX_TOKENS,
    LESSON_PLAN_TEMPERATURE,
    MAIN_MODEL_MAX_TOKENS,
    MAIN_MODEL_TEMPERATURE,
)


class Executor:
    def __init__(self, *, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_env()

    async def execute_step(self, step: PlanStep, *, context: CompressedContext) -> StepResult:
        tool = (step.tool or "").strip()
        handler = getattr(self, f"_tool_{tool}", None)
        if handler is None:
            return StepResult(step_id=step.id, tool=tool, success=False, error=f"Unknown tool: {tool}")

        try:
            output = await handler(step.arguments or {}, context)
            return StepResult(step_id=step.id, tool=tool, success=True, output=output)
        except Exception as exc:  # pragma: no cover (best-effort safety)
            return StepResult(step_id=step.id, tool=tool, success=False, error=str(exc))

    async def _call_llm_text(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = LESSON_PLAN_TEMPERATURE,
        max_tokens: int = LESSON_PLAN_MAX_TOKENS,
    ) -> str:
        if not LESSON_PLAN_API_KEY:
            return ""
        headers = {"Authorization": f"Bearer {LESSON_PLAN_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=float(API_TIMEOUT or 120)) as client:
            resp = await client.post(
                f"{LESSON_PLAN_BASE_URL.rstrip('/')}/chat/completions", headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except Exception:
            return ""

    def _extract_json_obj(self, text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            return {}
        # Strip markdown code fences.
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

    def _pick_questions(self, questions: List[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
        cleaned: List[Tuple[int, Dict[str, Any]]] = []
        for q in questions:
            stem = str(q.get("stem") or "")
            if not stem or len(stem) < 8:
                continue
            # Prefer fewer images and reasonable length.
            penalty = 0
            penalty += stem.count("[图片:") * 50
            penalty += max(0, len(stem) - 500) // 20
            cleaned.append((penalty, q))
        cleaned.sort(key=lambda x: x[0])
        return [q for _, q in cleaned[: max(1, limit)]]

    async def _tool_retrieve_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()

        if not LESSON_PLAN_API_KEY:
            return {
                "topic": topic,
                "subject": subject,
                "difficulty": difficulty,
                "definition": "",
                "key_points": [],
                "prerequisites": [],
                "common_mistakes": [],
                "methods": [],
                "source": "fallback",
                "note": "未配置模型，知识检索返回为空。",
            }

        prompt = f"""请为“{subject}”的知识点“{topic}”生成可用于自学资料的事实性要点。\n\n要求：\n- 输出严格 JSON（不要 Markdown、不要代码块）\n- 字段：definition(str), key_points(str[]), prerequisites(str[]), common_mistakes(str[]), methods(str[])\n- 难度参考：{difficulty}\n"""
        text = await self._call_llm_text(
            messages=[{"role": "system", "content": "你是严谨的学科老师，输出必须是JSON。"}, {"role": "user", "content": prompt}],
            model=self.config.summarizer_model,
            temperature=0.2,
            max_tokens=900,
        )
        obj = self._extract_json_obj(text)
        return {
            "topic": topic,
            "subject": subject,
            "difficulty": difficulty,
            "definition": str(obj.get("definition") or ""),
            "key_points": list(obj.get("key_points") or []),
            "prerequisites": list(obj.get("prerequisites") or []),
            "common_mistakes": list(obj.get("common_mistakes") or []),
            "methods": list(obj.get("methods") or []),
            "source": "llm",
        }

    async def _tool_search_examples(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()
        limit = int(args.get("limit") or 3)
        limit = max(1, min(5, limit))

        crawler = await get_crawler(subject=subject)
        res = await crawler.search_by_keyword(
            keyword=topic,
            subject=subject or crawler.subject,
            limit=max(12, limit * 4),
            difficulty=difficulty,
            max_pages=2,
            dedup_by_stem=True,
            min_quality_score=10,
            with_quality=True,
            strict_subject=True,
            require_difficulty=True,
        )
        questions = list(res.get("questions") or []) if isinstance(res, dict) else []
        picked = self._pick_questions(questions, limit=limit)
        return {"topic": topic, "subject": subject or crawler.subject, "difficulty": difficulty, "examples": picked}

    async def _tool_search_exercises(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()
        limit = int(args.get("limit") or 10)
        limit = max(5, min(30, limit))

        used_ids: set[str] = set()
        prev = ctx.working_memory.get("search_examples")
        if isinstance(prev, dict):
            for q in prev.get("examples") or []:
                qid = str(q.get("question_id") or "").strip()
                if qid:
                    used_ids.add(qid)

        crawler = await get_crawler(subject=subject)
        res = await crawler.search_by_keyword(
            keyword=topic,
            subject=subject or crawler.subject,
            limit=max(20, limit * 3),
            difficulty=difficulty,
            max_pages=2,
            dedup_by_stem=True,
            min_quality_score=10,
            with_quality=True,
            strict_subject=True,
            require_difficulty=True,
        )
        questions = list(res.get("questions") or []) if isinstance(res, dict) else []
        filtered = [q for q in questions if str(q.get("question_id") or "").strip() not in used_ids]
        picked = self._pick_questions(filtered, limit=limit)
        return {"topic": topic, "subject": subject or crawler.subject, "difficulty": difficulty, "exercises": picked}

    async def _tool_analyze_topic(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        knowledge = ctx.working_memory.get("retrieve_knowledge") if isinstance(ctx.working_memory.get("retrieve_knowledge"), dict) else {}

        if not LESSON_PLAN_API_KEY:
            return {
                "topic": topic,
                "subject": subject,
                "outline": ["概念与定义", "常用方法", "例题精讲", "分层练习"],
                "confusions": [],
                "source": "fallback",
            }

        prompt = {
            "topic": topic,
            "subject": subject,
            "knowledge": knowledge,
            "required_output": {
                "outline": "string[]",
                "confusions": "string[]",
                "teaching_order": "string[]",
            },
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的教学设计专家，输出必须是JSON。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.planner_model,
            temperature=0.2,
            max_tokens=900,
        )
        obj = self._extract_json_obj(text)
        return {
            "topic": topic,
            "subject": subject,
            "outline": list(obj.get("outline") or []),
            "confusions": list(obj.get("confusions") or []),
            "teaching_order": list(obj.get("teaching_order") or []),
            "source": "llm",
        }

    async def _tool_generate_explanation(self, args: Dict[str, Any], ctx: CompressedContext) -> str:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        knowledge = ctx.working_memory.get("retrieve_knowledge") if isinstance(ctx.working_memory.get("retrieve_knowledge"), dict) else {}
        analysis = ctx.working_memory.get("analyze_topic") if isinstance(ctx.working_memory.get("analyze_topic"), dict) else {}

        if not LESSON_PLAN_API_KEY:
            return (
                f"## 一、知识点讲解：{topic}\n\n"
                "（未配置模型，无法生成详细讲解。你可以先配置 `.env` 中的 `LESSON_PLAN_*` 后重试。）\n"
            )

        prompt = {
            "topic": topic,
            "subject": subject,
            "knowledge": knowledge,
            "analysis": analysis,
            "instructions": "请生成 Markdown 章节：知识点讲解。包含：定义、关键点、常见误区、方法小结。不要输出练习题。",
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的自学资料编写老师，输出必须是Markdown。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.planner_model,
            temperature=0.4,
            max_tokens=1400,
        )
        return text.strip()

    async def _tool_generate_solutions(self, args: Dict[str, Any], ctx: CompressedContext) -> List[Dict[str, Any]]:
        max_examples = int(args.get("max_examples") or 3)
        max_examples = max(1, min(5, max_examples))

        prev = ctx.working_memory.get("search_examples")
        examples: List[Dict[str, Any]] = []
        if isinstance(prev, dict):
            for q in prev.get("examples") or []:
                if isinstance(q, dict):
                    examples.append(q)
        examples = examples[:max_examples]

        if not examples:
            return []

        if not LESSON_PLAN_API_KEY:
            return [
                {
                    "question_id": q.get("question_id"),
                    "stem": q.get("stem"),
                    "solution_markdown": "（未配置模型，无法生成解答。）",
                }
                for q in examples
            ]

        solutions: List[Dict[str, Any]] = []
        for idx, q in enumerate(examples, start=1):
            stem = str(q.get("stem") or "").strip()
            prompt = f"""请为下面例题写出详细分步解答（Markdown）。\n\n要求：\n- 每一步说明在做什么\n- 如果题干信息不足，请说明需要补充什么\n\n题目：\n{stem}\n"""
            sol = await self._call_llm_text(
                messages=[
                    {"role": "system", "content": "你是严谨的数学解题老师，输出必须是Markdown。"},
                    {"role": "user", "content": prompt},
                ],
                model=self.config.planner_model,
                temperature=0.3,
                max_tokens=1200,
            )
            solutions.append(
                {
                    "index": idx,
                    "question_id": q.get("question_id"),
                    "source": q.get("source"),
                    "difficulty": q.get("difficulty"),
                    "stem": stem,
                    "solution_markdown": (sol or "").strip(),
                }
            )
        return solutions

    async def _tool_assemble_markdown(self, args: Dict[str, Any], ctx: CompressedContext) -> str:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()

        knowledge = ctx.working_memory.get("retrieve_knowledge") if isinstance(ctx.working_memory.get("retrieve_knowledge"), dict) else {}
        explanation = ctx.working_memory.get("generate_explanation")
        solutions = ctx.working_memory.get("generate_solutions")
        exercises = ctx.working_memory.get("search_exercises") if isinstance(ctx.working_memory.get("search_exercises"), dict) else {}

        lines: List[str] = []
        lines.append(f"# 自学材料：{topic}")
        if subject:
            lines.append("")
            lines.append(f"> 学科：{subject}")

        # Knowledge block (structured) + explanation block (markdown)
        definition = str(knowledge.get("definition") or "").strip()
        key_points = knowledge.get("key_points") if isinstance(knowledge.get("key_points"), list) else []
        prereq = knowledge.get("prerequisites") if isinstance(knowledge.get("prerequisites"), list) else []
        mistakes = knowledge.get("common_mistakes") if isinstance(knowledge.get("common_mistakes"), list) else []
        methods = knowledge.get("methods") if isinstance(knowledge.get("methods"), list) else []

        lines.append("")
        lines.append("## 一、知识点讲解")
        lines.append("")
        if definition:
            lines.append("### 1) 定义")
            lines.append("")
            lines.append(definition)
            lines.append("")
        if key_points:
            lines.append("### 2) 关键点")
            lines.append("")
            for x in key_points:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")
        if prereq:
            lines.append("### 3) 前置知识")
            lines.append("")
            for x in prereq:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")
        if mistakes:
            lines.append("### 4) 常见误区")
            lines.append("")
            for x in mistakes:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")
        if methods:
            lines.append("### 5) 方法小结")
            lines.append("")
            for x in methods:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")

        if isinstance(explanation, str) and explanation.strip():
            lines.append("### 6) 讲解稿")
            lines.append("")
            lines.append(explanation.strip())
            lines.append("")

        # Examples + solutions
        lines.append("## 二、例题精讲（含步骤）")
        lines.append("")
        if isinstance(solutions, list) and solutions:
            for item in solutions:
                stem = str(item.get("stem") or "").strip()
                sol_md = str(item.get("solution_markdown") or "").strip()
                idx = item.get("index") or ""
                lines.append(f"### 例题 {idx}".strip())
                lines.append("")
                if stem:
                    lines.append("**题目**：")
                    lines.append("")
                    lines.append(stem)
                    lines.append("")
                if sol_md:
                    lines.append("**解答**：")
                    lines.append("")
                    lines.append(sol_md)
                    lines.append("")
                else:
                    lines.append("（未生成解答）")
                    lines.append("")
        else:
            examples = ctx.working_memory.get("search_examples")
            if isinstance(examples, dict) and examples.get("examples"):
                for i, q in enumerate(examples.get("examples") or [], start=1):
                    if not isinstance(q, dict):
                        continue
                    lines.append(f"### 例题 {i}")
                    lines.append("")
                    lines.append(str(q.get("stem") or "").strip())
                    lines.append("")
            else:
                lines.append("（未检索到例题）")
                lines.append("")

        # Exercises (no solutions)
        lines.append("## 三、练习题（不含答案）")
        lines.append("")
        ex_list = exercises.get("exercises") if isinstance(exercises.get("exercises"), list) else []
        if ex_list:
            for i, q in enumerate(ex_list, start=1):
                if not isinstance(q, dict):
                    continue
                stem = str(q.get("stem") or "").strip()
                if not stem:
                    continue
                lines.append(f"{i}. {stem}")
                lines.append("")
        else:
            lines.append("（未检索到练习题）")
            lines.append("")

        markdown = "\n".join(lines).strip() + "\n"
        ctx.working_memory["markdown"] = markdown
        return markdown

    async def _tool_review_content(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        markdown = str(ctx.working_memory.get("markdown") or "")

        if not LESSON_PLAN_API_KEY:
            return {"passed": True, "issues": [], "suggestions": [], "source": "fallback"}

        prompt = f"""请审查下面这份自学资料 Markdown，找出：\n1) 逻辑跳跃/不清晰处\n2) 可能的错误或表述不严谨\n3) 建议改进点（最多5条）\n\n要求：输出严格 JSON（不要 Markdown）。字段：passed(bool), issues(string[]), suggestions(string[])\n\n主题：{topic}\n\nMarkdown:\n{markdown}\n"""
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的审稿人，输出必须是JSON。"},
                {"role": "user", "content": prompt},
            ],
            model=self.config.reflector_model,
            temperature=0.1,
            max_tokens=900,
        )
        obj = self._extract_json_obj(text)
        return {
            "passed": bool(obj.get("passed")) if "passed" in obj else True,
            "issues": list(obj.get("issues") or []),
            "suggestions": list(obj.get("suggestions") or []),
            "source": "llm",
        }

    async def _tool_revise_markdown(self, args: Dict[str, Any], ctx: CompressedContext) -> str:
        issues = args.get("issues") or []
        markdown = str(ctx.working_memory.get("markdown") or "")
        if not markdown:
            markdown = str(ctx.working_memory.get("assemble_markdown") or "")

        if not LESSON_PLAN_API_KEY or not markdown:
            return markdown

        prompt = {
            "issues": issues,
            "instructions": "请根据 issues 修订 Markdown，保持结构：讲解→例题→练习题（练习题不含答案）。仅输出修订后的Markdown。",
            "markdown": markdown,
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的自学资料编辑，输出必须是Markdown。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.planner_model,
            temperature=0.2,
            max_tokens=1600,
        )
        revised = (text or "").strip()
        if revised:
            ctx.working_memory["markdown"] = revised
            return revised
        return markdown

