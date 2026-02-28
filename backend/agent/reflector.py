from __future__ import annotations

import json
from typing import Optional

from backend.agent.config import AgentConfig
from backend.agent.types import ActionResults, CompressedContext, ExecutionPlan, ReflectionResult
from backend.core.llm_client import chat_completion_text


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

        normalized_model = str(self.config.reflector_model or "").strip()
        if not normalized_model:
            return ReflectionResult(passed=True, summary="审查通过（未配置审查模型，跳过）")

        facts_by_kp = {}
        facts_raw = context.working_memory.get("source_facts")
        if isinstance(facts_raw, dict):
            for kp, facts in list(facts_raw.items())[:10]:
                if not isinstance(facts, list):
                    continue
                hi = []
                lo = []
                for f in facts[:24]:
                    if not isinstance(f, dict):
                        continue
                    fact = str(f.get("fact") or "").strip()
                    if not fact:
                        continue
                    try:
                        conf = float(f.get("confidence") or 0.0)
                    except Exception:
                        conf = 0.0
                    item = {"fact": (fact[:180].rstrip() + "…") if len(fact) > 180 else fact, "confidence": conf}
                    if conf >= 0.7 and len(hi) < 5:
                        hi.append(item)
                    elif 0.4 <= conf < 0.7 and len(lo) < 3:
                        lo.append(item)
                if hi or lo:
                    facts_by_kp[str(kp).strip() or "（未知知识点）"] = {"high_confidence": hi, "low_confidence": lo}

        prompt = (
            "请审查下面的自学资料 Markdown 是否满足：\n"
            "- 结构是否清晰（按知识点分段；讲解逻辑顺畅）\n"
            "- 是否覆盖关键维度：动机/直观、定义/表述、性质/结论、条件/适用范围、反例/边界、常见误区、应用/题型\n"
            "- 是否有明显事实/逻辑错误，或过度强断言\n"
            "- 若提供了 facts_by_kp：检查内容是否与高置信度事实矛盾；低置信度事实相关表述需用“推断/可能/建议”等措辞\n"
            "\n"
            "输出严格 JSON（不要 Markdown）。字段：passed(bool), issues(string[]), suggestions(string[])\n"
            "\n"
            f"主题：{topic}\n\n"
            f"facts_by_kp（可为空）：{json.dumps(facts_by_kp, ensure_ascii=False)}\n\n"
            f"Markdown:\n{markdown}\n"
        )
        try:
            content = await chat_completion_text(
                messages=[
                    {"role": "system", "content": "你是严谨的审稿人，输出必须是JSON。"},
                    {"role": "user", "content": prompt},
                ],
                model=normalized_model,
                temperature=0.1,
                max_tokens=900,
                retries=3,
                req_id_prefix="reflect",
            )
        except Exception:
            content = ""

        content = str(content or "")
        if not content.strip():
            return ReflectionResult(passed=True, summary="审查通过（审查模型未返回内容，跳过）")

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

