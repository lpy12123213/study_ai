from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.core.text_lint import lint_text
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry


def _content_review_system_prompt() -> str:
    return create_default_prompt_registry().render("agent.tool.content_review.v1").content


def _markdown_revision_system_prompt() -> str:
    return create_default_prompt_registry().render("agent.tool.markdown_revision.v1").content


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

        empty_sections = ctx.working_memory.get("study_empty_sections")
        if isinstance(empty_sections, list):
            names = [str(x or "").strip() for x in empty_sections if str(x or "").strip()]
            if names:
                heuristic_issues.append(
                    "以下知识点讲解为空或使用兜底内容，必须重写后再进入交付：" + "、".join(names[:8])
                )

        lint_flags = lint_text(markdown)
        if lint_flags:
            heuristic_issues.append("Markdown 存在生成残留或结构问题：" + ", ".join(lint_flags[:6]))

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
                            f"知识点《{kp}》web_search 结果质量偏低（avg_snippet≈{avg_snippet}字，命中率={kp_match_n}/{web_n}）。"
                            f"建议优化策略：\n"
                            f"  1) 细化 query_hint：添加「定义」「必要条件」「充分条件」「反例」「证明思路」「典型应用」等维度关键词；\n"
                            f"  2) 多轮搜索：针对该知识点补充 2-3 轮不同角度的搜索（理论/实践/案例）；\n"
                            f"  3) 深度抓取：对排名靠前的高质量链接启用 browse_web_pages 获取完整正文；\n"
                            f"  4) 交叉验证：结合 wikipedia_search 或 stackexchange_search 补充权威解释。"
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

                        _dim("动机/直观", r"(动机|为什么|意义|背景|直观|intuition|引入|起源|由来|缘由)")
                        _dim("定义/概念", r"(定义|概念|是什么|含义|本质|内涵|外延|界定)")
                        _dim("性质/结论", r"(性质|结论|定理|推论|关键结论|重要结论|特点|特性|规律|法则)")
                        _dim("条件/适用范围", r"(条件|适用|前提|范围|成立|约束|限制|假设|要求)")
                        _dim("反例/边界", r"(反例|边界|极端|陷阱|特例|例外|临界|极限情况)")
                        _dim("误区/易错点", r"(误区|易错|注意|常见错误|混淆|辨析|区分|对比)")
                        _dim("应用/题型", r"(应用|题型|例题|典型|场景|实例|案例|练习|解题)")
                        _dim("推导/证明", r"(推导|证明|演算|论证|证法|步骤)")
                        _dim("联系/拓展", r"(联系|拓展|延伸|相关|对比|类比|推广|深入)")

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
                    except (TypeError, ValueError):
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
                "Strictly review the content quality of the following self-study Markdown material.",
                "Review focus:",
                "1. 结构完整性：是否包含动机引入、核心定义、关键性质、适用条件、边界情况、常见误区、应用场景等必要模块。",
                "2. 逻辑自洽性：论述是否前后一致，推理链条是否完整，是否存在跳跃或矛盾。",
                "3. 事实准确性：如提供 facts_by_kp，检查内容是否与高置信度(>=0.7)事实矛盾；涉及低置信度事实时，表述应使用'可能/推测/有待验证'等限定词。",
                "4. 深度适配性：讲解深度是否匹配目标受众，是否避免了过度简化或不必要的复杂化。",
                "5. 维度覆盖：如提供 dimensions，逐一检查各维度是否得到充分覆盖，指出明显缺失的维度。",
                "Output requirements:",
                "- issues: 列出 3~8 条最关键的问题，每条问题需具体指出位置和性质。",
                "- suggestions: 针对每条 issue 给出可执行的修改建议。",
                "- passed: 若无严重问题（事实错误、逻辑矛盾、关键遗漏）则为 true，否则为 false。",
                "Output strict JSON: {\"passed\": bool, \"issues\": [string], \"suggestions\": [string]}",
            ],
            "markdown": markdown,
            "dimensions": dimensions,
            "facts_by_kp": facts_by_kp,
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": _content_review_system_prompt()},
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
                "You are a professional academic content editor. Precisely revise the Markdown self-study material according to the review issues below:",
                "修订原则：",
                "1. 针对性修改：仅修正 issues 中明确指出的问题，不做无关改动。",
                "2. 事实准确：修正任何事实性错误，确保表述与权威来源一致。",
                "3. 逻辑完整：补齐缺失的前提条件、适用范围、边界情况说明。",
                "4. 结构清晰：保持原有章节层次，必要时可微调段落顺序以增强连贯性。",
                "5. 表述严谨：对不确定内容使用'可能/通常/在某些情况下'等限定词。",
                "6. Formatting: keep Markdown syntax correct and preserve complete code-block, formula, and list formatting.",
                "Output the complete revised Markdown document directly. Do not output JSON or add explanations."
            ),
            "markdown": markdown,
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": _markdown_revision_system_prompt()},
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
