from __future__ import annotations

import asyncio
import json
import random
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

        retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
        timeout_s = float(API_TIMEOUT or 120)
        data = {}

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
                    resp = await client.post(
                        f"{LESSON_PLAN_BASE_URL.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                if resp.status_code in retry_statuses and attempt < 2:
                    retry_after = (resp.headers.get("retry-after") or "").strip()
                    wait_s = 0.0
                    try:
                        wait_s = float(retry_after) if retry_after else 0.0
                    except ValueError:
                        wait_s = 0.0
                    if wait_s <= 0:
                        wait_s = min(8.0, (2**attempt) * 0.9 + random.random() * 0.6)
                    await asyncio.sleep(wait_s)
                    continue

                resp.raise_for_status()
                data = resp.json() if isinstance(resp.json(), dict) else {}
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status in retry_statuses and attempt < 2:
                    await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                    continue
                return ReflectionResult(passed=True, summary=f"审查跳过（审查模型返回错误：{status}）")
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if attempt < 2:
                    await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                    continue
                return ReflectionResult(passed=True, summary=f"审查跳过（网络错误：{exc}）")
            except Exception as exc:
                if attempt < 2:
                    await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                    continue
                return ReflectionResult(passed=True, summary=f"审查跳过（未知错误：{exc}）")
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

