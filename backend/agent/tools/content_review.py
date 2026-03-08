from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.core.llm_client import is_llm_configured


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
        dimensions: Dict[str, Dict[str, Any]] = {}

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

            # When we already have generated markdown, additionally enforce "dimension coverage"
            # for deep/research presets so iteration is driven by concrete gaps (conditions/edge cases/applications).
            md_sections_by_kp: Dict[str, str] = {}
            if markdown.strip():
                current_kp = ""
                buf: List[str] = []
                for line in markdown.splitlines():
                    m = re.match(r"^##\s+\d+、\s*(.+?)\s*$", line.strip())
                    if m:
                        if current_kp:
                            md_sections_by_kp[current_kp] = "\n".join(buf).strip()
                        current_kp = str(m.group(1) or "").strip()
                        buf = []
                        continue
                    if current_kp:
                        buf.append(line)
                if current_kp and current_kp not in md_sections_by_kp:
                    md_sections_by_kp[current_kp] = "\n".join(buf).strip()

            source_facts = ctx.working_memory.get("source_facts")
            source_facts = dict(source_facts) if isinstance(source_facts, dict) else {}

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

                sources_ok = (
                    bool(wiki_summary or mw_summary) or web_n >= min_web or pages_n >= 1 or se_n >= 1 or gh_n >= 1
                )
                if enforce_sources and not sources_ok:
                    heuristic_issues.append(
                        f"知识点《{kp}》资料来源不足：建议增加 web_search_knowledge 轮次，并补充 query_hint（定义/性质/反例/证明/应用）。"
                    )

                # Retrieval quality heuristic: avoid counting "almost empty" snippets as sufficient coverage.
                web_blob = it.get("web_search") if isinstance(it.get("web_search"), dict) else {}
                web_results = web_blob.get("results") if isinstance(web_blob.get("results"), list) else []
                snippet_lens: List[int] = []
                kp_match_n = 0
                for r in [x for x in web_results if isinstance(x, dict)][:10]:
                    title = str(r.get("title") or "").strip()
                    snippet = str(r.get("snippet") or r.get("description") or r.get("text") or "").strip()
                    if snippet:
                        snippet_lens.append(len(snippet))
                    hay = f"{title} {snippet}"
                    if kp and len(kp) >= 2 and kp in hay:
                        kp_match_n += 1
                avg_snippet = int(sum(snippet_lens) / len(snippet_lens)) if snippet_lens else 0
                if enforce_sources and web_n >= min_web and not (wiki_summary or mw_summary) and pages_n <= 0:
                    if preset in {"deep", "research"} and (avg_snippet < 40 or (kp_match_n <= 0 and web_n >= 3)):
                        heuristic_issues.append(
                            f"知识点《{kp}》web_search 结果质量偏低（avg_snippet≈{avg_snippet}，match={kp_match_n}/{web_n}）。"
                            "建议优化 query_hint（条件/反例/推导/应用）并补抓 1 轮，必要时启用 browse_web_pages。"
                        )
                    elif avg_snippet < 30:
                        heuristic_suggestions.append(
                            f"建议：知识点《{kp}》web_search 结果较空（avg_snippet≈{avg_snippet}），可补充更具体 query_hint 提升相关性。"
                        )

                # Dimension coverage report (observable per knowledge point).
                if md_sections_by_kp:
                    sec = md_sections_by_kp.get(kp, "")
                    if sec:
                        missing_dims: List[str] = []
                        present_dims: List[str] = []

                        def _dim(name: str, pattern: str) -> None:
                            if re.search(pattern, sec):
                                present_dims.append(name)
                            else:
                                missing_dims.append(name)

                        _dim("动机/直观", r"(动机|为什么|意义|背景|直观|intuition|引入)")
                        _dim("定义/概念", r"(定义|概念|是什么)")
                        _dim("性质/结论", r"(性质|结论|定理|推论|关键结论|重要结论|特点)")
                        _dim("条件/适用范围", r"(条件|适用|前提|范围|成立)")
                        _dim("反例/边界", r"(反例|边界|极端|陷阱)")
                        _dim("误区/易错点", r"(误区|易错|注意|常见错误)")
                        _dim("应用/题型", r"(应用|题型|例题|典型|场景)")

                        facts_total = 0
                        facts_raw = source_facts.get(kp)
                        if isinstance(facts_raw, list):
                            facts_total = len(
                                [x for x in facts_raw if isinstance(x, dict) and str(x.get("fact") or "").strip()]
                            )

                        dimensions[kp] = {"present": present_dims, "missing": missing_dims, "facts_total": facts_total}

                        # Deep/research: missing too many dimensions should fail the review to trigger targeted rework.
                        if enforce_sources and preset in {"deep", "research"}:
                            allowed_missing = 2 if preset == "deep" else 1
                            if len(missing_dims) > allowed_missing:
                                heuristic_issues.append(
                                    f"知识点《{kp}》覆盖维度不足：缺少 {', '.join(missing_dims[:3])}。建议补充检索并重写该知识点讲解。"
                                )
                        elif len(missing_dims) >= 4:
                            heuristic_suggestions.append(
                                f"建议：知识点《{kp}》覆盖维度偏少：缺少 {', '.join(missing_dims[:3])}。可做定向补全修订。"
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
                "dimensions": dimensions,
            }

        if not is_llm_configured():
            if strict_llm:
                raise RuntimeError("llm_not_configured")
            return {"passed": True, "issues": [], "suggestions": [], "source": "fallback", "dimensions": dimensions}

        facts_by_kp: Dict[str, Any] = {}
        facts_raw = ctx.working_memory.get("source_facts")
        if isinstance(facts_raw, dict):
            for kp, facts in list(facts_raw.items())[:12]:
                if not isinstance(facts, list):
                    continue
                hi: List[Dict[str, Any]] = []
                lo: List[Dict[str, Any]] = []
                for f in facts[:32]:
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
                    if conf >= 0.7 and len(hi) < 6:
                        hi.append(item)
                    elif 0.4 <= conf < 0.7 and len(lo) < 4:
                        lo.append(item)
                if hi or lo:
                    facts_by_kp[str(kp).strip() or "（未知知识点）"] = {"high_confidence": hi, "low_confidence": lo}

        prompt = {
            "topic": topic,
            "requirements": [
                "请审查下面的 Markdown 内容质量。",
                "关注：结构是否清晰、讲解是否自洽、是否遗漏关键前提/适用条件/边界反例/常见误区/应用场景、是否有明显事实/逻辑错误。",
                "如提供了 dimensions：请优先指出覆盖维度缺口（动机/定义/性质/条件/反例/误区/应用）。",
                "如提供了 facts_by_kp：请检查 Markdown 是否与高置信度事实矛盾；低置信度事实相关表述需避免强断言（用“推断/可能/建议”）。",
                "给出最关键的 3~8 条问题（issues），以及对应的修改建议（suggestions）。",
                "只输出严格 JSON：passed(bool), issues(string[]), suggestions(string[])。",
            ],
            "markdown": markdown,
            "dimensions": dimensions,
            "facts_by_kp": facts_by_kp,
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
            "dimensions": dimensions,
        }

    async def _tool_revise_markdown(self, args: Dict[str, Any], ctx: CompressedContext) -> str:
        issues = args.get("issues") or []
        markdown = str(ctx.working_memory.get("markdown") or "")
        if not markdown:
            markdown = str(ctx.working_memory.get("assemble_markdown") or "")

        if not is_llm_configured() or not markdown:
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
