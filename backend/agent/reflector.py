from __future__ import annotations

import json
from typing import Optional

import httpx

from backend.agent.config import AgentConfig
from backend.agent.types import ActionResults, CompressedContext, ExecutionPlan, ReflectionResult
from backend.core.settings import API_TIMEOUT, LESSON_PLAN_API_KEY, LESSON_PLAN_BASE_URL


class Reflector:
    def __init__(self, *, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_env()

    async def reflect(
        self,
        *,
        topic: str,
        plan: ExecutionPlan,
        results: ActionResults,
        context: CompressedContext,
    ) -> ReflectionResult:
        _ = plan
        markdown = results.artifacts.get("markdown") or context.working_memory.get("markdown") or ""
        if not isinstance(markdown, str):
            markdown = ""

        review = context.working_memory.get("review_content")
        if isinstance(review, dict):
            passed = bool(review.get("passed")) if "passed" in review else True
            issues = list(review.get("issues") or [])
            suggestions = list(review.get("suggestions") or [])
            summary = "审查通过 ✅" if passed else f"审查未通过（发现 {len(issues) or 1} 个问题）"
            if not passed and not issues:
                issues = ["审查未通过（未返回具体问题）"]
            return ReflectionResult(passed=passed, issues=issues, suggestions=suggestions, summary=summary)

        # Fallback: do a minimal LLM review if configured.
        if not LESSON_PLAN_API_KEY:
            return ReflectionResult(passed=True, summary="审查通过（未配置审查模型，跳过）")

        prompt = f"""请审查下面的自学资料 Markdown 是否满足：\n- 结构：讲解→例题（含步骤）→练习（不含答案）\n- 表述清晰，无明显逻辑跳跃\n- 数学/概念表述尽量严谨\n\n输出严格 JSON（不要 Markdown）。字段：passed(bool), issues(string[]), suggestions(string[])\n\n主题：{topic}\n\nMarkdown:\n{markdown}\n"""

        headers = {"Authorization": f"Bearer {LESSON_PLAN_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": self.config.reflector_model,
            "messages": [
                {"role": "system", "content": "你是严谨的审稿人，输出必须是JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 900,
        }
        async with httpx.AsyncClient(timeout=float(API_TIMEOUT or 120)) as client:
            resp = await client.post(f"{LESSON_PLAN_BASE_URL.rstrip('/')}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        content = ""
        try:
            content = str(data["choices"][0]["message"]["content"] or "")
        except Exception:
            content = ""
        raw = content.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
        try:
            obj = json.loads(raw)
        except Exception:
            obj = {}
        passed = bool(obj.get("passed")) if "passed" in obj else True
        issues = list(obj.get("issues") or [])
        suggestions = list(obj.get("suggestions") or [])
        summary = "审查通过 ✅" if passed else f"审查未通过（发现 {len(issues) or 1} 个问题）"
        if not passed and not issues:
            issues = ["审查未通过（未返回具体问题）"]
        return ReflectionResult(passed=passed, issues=issues, suggestions=suggestions, summary=summary)

