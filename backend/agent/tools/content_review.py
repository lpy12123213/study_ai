from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.core.settings import LESSON_PLAN_API_KEY, MOONSHOT_API_KEY


class ContentReviewToolsMixin:
    async def _tool_review_content(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        markdown = str(ctx.working_memory.get("markdown") or "")
        strict_llm = self._strict_llm(ctx, args)

        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        preset = str(study_opts.get("preset") or "").strip().lower()
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = ""

        # Heuristic checks (source coverage) to encourage deep research iterations.
        # We only fail the review when at least some upstream retrieval worked; otherwise we'd loop
        # endlessly on missing API keys/network constraints.
        heuristic_issues: List[str] = []
        heuristic_suggestions: List[str] = []

        aggregated = ctx.working_memory.get("aggregated") or ctx.working_memory.get("aggregate_knowledge")
        if isinstance(aggregated, dict) and isinstance(aggregated.get("items"), list):
            items = [x for x in (aggregated.get("items") or []) if isinstance(x, dict)]

            def _count_list(obj: Any, key: str) -> int:
                if not isinstance(obj, dict):
                    return 0
                v = obj.get(key)
                return len(v) if isinstance(v, list) else 0

            any_web = any(_count_list(it.get("web_search"), "results") > 0 for it in items)
            any_wiki = any(
                str((it.get("wikipedia") or {}).get("summary") or "").strip()
                or str((it.get("mediawiki") or {}).get("summary") or "").strip()
                for it in items
                if isinstance(it, dict)
            )
            any_stackexchange = any(_count_list(it.get("stackexchange"), "results") > 0 for it in items)

            enforce_sources = any_web or any_wiki or any_stackexchange

            for it in items:
                kp = str(it.get("knowledge_point") or "").strip() or "（未知知识点）"

                wiki_summary = str((it.get("wikipedia") or {}).get("summary") or "").strip()
                mw_summary = str((it.get("mediawiki") or {}).get("summary") or "").strip()

                web_n = _count_list(it.get("web_search"), "results")
                pages_n = _count_list(it.get("web_pages"), "pages")
                se_n = _count_list(it.get("stackexchange"), "results")
                gh_n = _count_list(it.get("github"), "results")

                min_web = 3
                if preset == "deep":
                    min_web = 4
                elif preset == "research":
                    min_web = 5

                sources_ok = bool(wiki_summary or mw_summary) or web_n >= min_web or pages_n >= 1 or se_n >= 1 or gh_n >= 1
                if enforce_sources and not sources_ok:
                    heuristic_issues.append(
                        f"知识点《{kp}》资料来源不足：建议增加 web_search_knowledge 轮次，并补充 query_hint（定义/性质/反例/证明/应用）。"
                    )

                if ctx.working_memory.get("search_questions_by_knowledge") is not None:
                    examples_n = _count_list((it.get("questions") or {}), "examples")
                    exercises_n = _count_list((it.get("questions") or {}), "exercises")
                    if examples_n + exercises_n <= 0:
                        heuristic_suggestions.append(
                            f"建议：知识点《{kp}》题库未命中例题/练习题，可增加检索轮次或放宽筛选条件。"
                        )

        if heuristic_issues:
            return {
                "passed": False,
                "issues": heuristic_issues[:8],
                "suggestions": heuristic_suggestions[:8],
                "source": "heuristic",
            }

        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            if strict_llm:
                raise RuntimeError("llm_not_configured")
            return {"passed": True, "issues": [], "suggestions": [], "source": "fallback"}

        prompt = {
            "topic": topic,
            "requirements": [
                "请审查下面的 Markdown 内容质量。",
                "关注：结构是否清晰、讲解是否自洽、是否遗漏关键前提/适用条件、是否有明显事实/逻辑错误。",
                "给出最关键的 3~8 条问题（issues），以及对应的修改建议（suggestions）。",
                "只输出严格 JSON：passed(bool), issues(string[]), suggestions(string[])。",
            ],
            "markdown": markdown,
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的内容审查员，只输出 JSON。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.reflector_model,
            temperature=0.1,
            max_tokens=2600,
            response_format={"type": "json_object"},
            raise_on_fail=strict_llm,
        )
        obj = self._extract_json_obj(text)
        if strict_llm and not obj:
            raise RuntimeError(f"llm_review_failed: invalid_json model={self.config.reflector_model}")
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

        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY) or not markdown:
            return markdown

        prompt = {
            "issues": issues,
            "instructions": (
                "请根据 issues 修订 Markdown，修正明显错误、补齐关键前提/适用条件，并保持整体结构清晰。"
                "只输出修订后的 Markdown（不要输出 JSON，不要解释）。"
            ),
            "markdown": markdown,
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的 Markdown 编辑，只输出最终 Markdown。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.planner_model,
            temperature=0.2,
            max_tokens=8000,
        )
        revised = (text or "").strip()
        if revised:
            ctx.working_memory["markdown"] = revised
            return revised
        return markdown

