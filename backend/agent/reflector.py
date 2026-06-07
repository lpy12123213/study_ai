from __future__ import annotations

import json
from typing import Optional

from backend.agent.config import AgentConfig
from backend.agent.types import ActionResults, CompressedContext, ExecutionPlan, ReflectionResult
from backend.core.logging_utils import get_logger
from backend.llm.client import chat_completion_text
from backend.llm.prompts import create_default_prompt_registry

logger = get_logger(__name__)


def _reflector_system_prompt() -> str:
    return create_default_prompt_registry().render("agent.reflector.study_materials.v1").content


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
                    except (TypeError, ValueError):
                        conf = 0.0
                    item = {"fact": (fact[:180].rstrip() + "…") if len(fact) > 180 else fact, "confidence": conf}
                    if conf >= 0.7 and len(hi) < 5:
                        hi.append(item)
                    elif 0.4 <= conf < 0.7 and len(lo) < 3:
                        lo.append(item)
                if hi or lo:
                    facts_by_kp[str(kp).strip() or "（未知知识点）"] = {"high_confidence": hi, "low_confidence": lo}

        outline_verify_by_kp = {}
        outlines_raw = context.working_memory.get("outlines")
        if isinstance(outlines_raw, dict):
            for kp, outline in list(outlines_raw.items())[:10]:
                if not isinstance(outline, dict):
                    continue
                secs_raw = outline.get("sections")
                if not isinstance(secs_raw, list):
                    continue
                secs = []
                for sec in secs_raw[:14]:
                    if not isinstance(sec, dict):
                        continue
                    title = str(sec.get("title") or "").strip()
                    verify_raw = sec.get("verify")
                    verify_list = (
                        [str(x).strip() for x in verify_raw if str(x).strip()][:6] if isinstance(verify_raw, list) else []
                    )
                    if not title and not verify_list:
                        continue
                    secs.append({"title": title or "（无标题）", "verify": verify_list})
                if secs:
                    outline_verify_by_kp[str(kp).strip() or "（未知知识点）"] = secs

        prompt = (
            "Review whether the self-study Markdown below satisfies:\n"
            "- 结构是否清晰（按知识点分段；讲解逻辑顺畅）\n"
            "- 覆盖度：根据知识点类型尽量覆盖核心定义/直观、关键性质与条件、常见误区、应用/题型；不适用可省略，但不应遗漏核心概念解释。\n"
            "- If outline_verify_by_kp is provided, use it as the primary review baseline. Merging, reordering, or omitting inapplicable items is allowed only if the verify intent is still satisfied.\n"
            "- 是否有明显事实/逻辑错误，或过度强断言\n"
            "- 若提供了 facts_by_kp：检查内容是否与高置信度事实矛盾；低置信度事实相关表述需用“推断/可能/建议”等措辞\n"
            "\n"
            "Output strict JSON, not Markdown. Fields: passed(bool), issues(string[]), suggestions(string[])\n"
            "\n"
            f"主题：{topic}\n\n"
            f"outline_verify_by_kp（可为空）：{json.dumps(outline_verify_by_kp, ensure_ascii=False)}\n\n"
            f"facts_by_kp（可为空）：{json.dumps(facts_by_kp, ensure_ascii=False)}\n\n"
            f"Markdown:\n{markdown}\n"
        )
        try:
            content = await chat_completion_text(
                messages=[
                    {"role": "system", "content": _reflector_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                model=normalized_model,
                temperature=0.1,
                max_tokens=900,
                retries=3,
                req_id_prefix="reflect",
            )
        except Exception as exc:
            logger.warning("reflector_llm_failed", extra={"error": str(exc)}, exc_info=True)
            return ReflectionResult(
                passed=False,
                issues=[f"审查模型调用失败：{str(exc) or 'unknown_error'}"],
                suggestions=[],
                summary="审查失败（审查模型调用异常）",
            )

        content = str(content or "")
        if not content.strip():
            return ReflectionResult(
                passed=False,
                issues=["审查模型未返回任何内容"],
                suggestions=[],
                summary="审查失败（审查模型未返回内容）",
            )

        raw = content.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
        try:
            obj = json.loads(raw)
        except Exception:
            logger.warning("reflector_llm_invalid_json", extra={"raw_preview": raw[:200]}, exc_info=True)
            return ReflectionResult(
                passed=False,
                issues=["审查模型返回内容无法解析为 JSON"],
                suggestions=[],
                summary="审查失败（审查模型输出无效）",
            )

        passed = bool(obj.get("passed")) if "passed" in obj else False
        issues = list(obj.get("issues") or [])
        suggestions = list(obj.get("suggestions") or [])
        summary = "审查通过 ✅" if passed else f"审查未通过（发现 {len(issues) or 1} 个问题）"
        if not passed and not issues:
            issues = ["审查未通过（未返回具体问题）"]
        return ReflectionResult(passed=passed, issues=issues, suggestions=suggestions, summary=summary)
