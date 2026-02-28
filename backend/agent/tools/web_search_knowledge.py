from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.agent.types import CompressedContext
from backend.agent.tools.deep_research import deep_research_exa
from backend.agent.tools.text_utils import _clip_text, _postprocess_web_search_result
from backend.core.settings import LESSON_PLAN_API_KEY, MOONSHOT_API_KEY


class WebSearchKnowledgeToolsMixin:
    async def _tool_web_search_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """网络搜索知识点（Exa 优先，可选 deepresearch 多轮；Metaso/智谱兜底）。

        - search_mode=deepresearch：Exa 多轮检索（breadth/depth）+ 学习要点/追问方向（需要 EXA_API_KEY）
        - search_mode=exa：Exa 直接搜索（可选拆分子问题），返回“搜索结果列表”
        - search_mode=metaso：强制使用 Metaso（ask/search），跳过 Exa
        - 注意：当显式设置 search_mode=exa/deepresearch 时，Exa 失败不会再自动回退到 Metaso
        - disable_metaso=true 或 STUDY_MATERIALS_DISABLE_METASO=1：禁用 Metaso（含兜底）
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        limit = int(args.get("limit") or 5)
        # Allow more per-knowledge-point calls when the user enables deeper presets; keep a safe upper bound.
        limit = max(1, min(limit, 25))
        query_hint = str(args.get("query_hint") or "").strip()
        scope = str(args.get("scope") or "webpage").strip() or "webpage"
        include_summary = bool(args.get("include_summary", True))
        text_max_length = int(args.get("text_max_length") or 2600)
        text_max_length = max(200, min(text_max_length, 8000))
        strict_llm = self._strict_llm(ctx, args)
        if strict_llm and not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            raise RuntimeError("llm_not_configured")

        # Study preset helps SubAgent choose better sub-questions and prompt style.
        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        preset = str(args.get("preset") or study_opts.get("preset") or os.getenv("STUDY_MATERIALS_PRESET") or "").strip().lower()
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = ""

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        from backend.mcp.metaso_search import metaso_ask, metaso_search

        def _env_truthy(name: str, default: bool = False) -> bool:
            raw = (os.getenv(name) or "").strip().lower()
            if not raw:
                return default
            return raw in {"1", "true", "yes", "y", "on"}

        disable_metaso_raw = args.get("disable_metaso")
        if disable_metaso_raw is None:
            disable_metaso = _env_truthy("STUDY_MATERIALS_DISABLE_METASO", False)
        else:
            disable_metaso = str(disable_metaso_raw).strip().lower() in {"1", "true", "yes", "y", "on"}

        def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
            try:
                n = int(value)
            except Exception:
                n = default
            return max(min_value, min(max_value, n))

        def _clean_metaso_answer(text: str) -> str:
            """Best-effort cleanup for Metaso /ask answers.

            Metaso often returns answers with:
            - blockquote prefixes (already handled in metaso_ask)
            - evidence markers like [[1]]
            - meta narration: "我需要/用户/证据/搜索到的资料..."
            """

            raw = (text or "").strip()
            if not raw:
                return ""

            # Drop simple evidence markers.
            raw = re.sub(r"\[\[\s*\d+\s*\]\]", "", raw)
            raw = re.sub(r"\(\[\[\s*\d+\s*\]\]\)", "", raw)
            # Keep newlines (Metaso answers are often structured); only collapse horizontal spaces/tabs.
            raw = re.sub(r"[ \t]{2,}", " ", raw).strip()

            meta_tokens = (
                "用户",
                "证据",
                "资料",
                "搜索到",
                "我需要",
                "我将",
                "让我",
                "Let's",
                "the user",
                "evidence",
            )
            content_markers = ("定义", "直观", "关键", "误区", "方法", "结论", "应用", "例", "注意")

            lines = [ln.rstrip() for ln in raw.splitlines()]
            out: List[str] = []
            started = False
            for ln in lines:
                s = (ln or "").strip()
                if not s:
                    continue

                # Skip leading meta narration before the first useful marker appears.
                if not started:
                    if any(tok in s for tok in content_markers):
                        started = True
                    elif any(tok in s for tok in meta_tokens) and len(s) <= 140:
                        continue
                    elif s.startswith(("好的", "Okay", "首先")) and len(s) <= 80:
                        continue

                # Skip in-body meta sentences that are short and clearly process narration.
                if any(tok in s for tok in meta_tokens) and len(s) <= 120:
                    continue

                out.append(s)

            cleaned = "\n".join(out).strip()
            # Avoid returning empty if our heuristic was too aggressive.
            return cleaned or raw

        async def _decompose_sub_questions(*, knowledge_point: str, base_query: str) -> List[str]:
            """Use the LLM (DeepSeek v3.2) to refine a broad knowledge point into smaller askable questions."""

            # Allow overriding the "thinking" model separately (some providers expose a thinking variant).
            thinking_model = str(
                os.getenv("STUDY_MATERIALS_THINKING_MODEL")
                or self.config.planner_model
                or self.config.summarizer_model
            ).strip()

            sub_n = _clamp_int(
                args.get("sub_questions"),
                default=_clamp_int(os.getenv("STUDY_MATERIALS_WEB_SUBQUERIES") or 4, default=4, min_value=2, max_value=25),
                min_value=2,
                max_value=25,
            )

            # If LLM isn't configured, fall back to a deterministic template split (non-strict only).
            if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                if strict_llm:
                    raise RuntimeError("llm_not_configured")
                tpl = [
                    f"{knowledge_point} 的定义与符号约定是什么？适用条件是什么？",
                    f"{knowledge_point} 的直观理解/几何意义是什么？",
                    f"{knowledge_point} 有哪些关键结论/性质？每条结论的使用前提是什么？",
                    f"{knowledge_point} 常见误区有哪些？各给一个反例或纠错点。",
                    f"{knowledge_point} 常用方法/步骤是什么？",
                    f"{knowledge_point} 有哪些等价表述/充分必要条件？容易混淆的相近概念是什么？",
                    f"{knowledge_point} 的边界情况/反例/不适用场景有哪些？",
                    f"{knowledge_point} 的推导/证明思路（非细节）应该怎样组织？",
                ]
                # Research presets: encourage deeper angles.
                if preset in {"deep", "research"}:
                    return tpl[:sub_n]
                return tpl[:sub_n]

            prompt = {
                "subject": subject,
                "knowledge_point": knowledge_point,
                "base_query": base_query,
                "query_hint": query_hint,
                "requirements": [
                    f"请将知识点拆成 {sub_n} 个适合向『联网问答 API』提问的子问题（每个子问题一句话）。",
                    "子问题要覆盖：定义/直观理解/关键结论与条件/常见误区/方法步骤（可合并，但要覆盖）。",
                    "尽量包含：等价表述/充分必要条件、边界情况/反例、不适用条件、与相近概念的区别（若适用）。"
                    if preset in {"deep", "research"}
                    else "（可选）如存在等价表述/边界情况/反例，也可作为子问题的一部分。",
                    "尽量包含：推导/证明思路的“骨架”（若适用）。" if preset in {"deep", "research"} else "（可选）需要时可补充推导/证明思路。",
                    "子问题要足够具体，避免泛泛而谈；每个子问题尽量能检索到不同角度的资料。",
                    "只输出严格 JSON，不要输出任何解释性文字。",
                ],
                "output_schema": {"sub_questions": ["string"]},
            }

            last_err = ""
            for attempt in range(3):
                text = await self._call_llm_text(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是严谨的知识探索助手（面向自学资料）。"
                                "请先在心里思考如何拆分问题，再只输出 JSON。"
                            ),
                        },
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    model=thinking_model,
                    temperature=0.2,
                    max_tokens=1600,
                    response_format={"type": "json_object"},
                    raise_on_fail=strict_llm,
                )
                obj = self._extract_json_obj(text)
                items = obj.get("sub_questions")
                if isinstance(items, list):
                    out = []
                    for it in items:
                        s = str(it or "").strip()
                        s = re.sub(r"\s+", " ", s)
                        if not s:
                            continue
                        if len(s) > 120:
                            s = s[:120].rstrip() + "…"
                        out.append(s)
                    # Ensure we always return something usable.
                    if len(out) >= 2:
                        return out[:sub_n]
                    last_err = f"too_few_items got={len(out)}"
                    if strict_llm and attempt < 2:
                        continue
                else:
                    last_err = "invalid_json"
                    if strict_llm and attempt < 2:
                        continue
                break

            if strict_llm:
                raise RuntimeError(f"llm_decompose_failed: {last_err or 'unknown'} model={thinking_model}")

            # LLM failed to follow schema; use templates as fallback.
            tpl = [
                f"{knowledge_point} 的定义与符号约定是什么？适用条件是什么？",
                f"{knowledge_point} 的直观理解/几何意义是什么？",
                f"{knowledge_point} 的关键结论/性质有哪些？每条结论的使用前提是什么？",
                f"{knowledge_point} 常见误区有哪些？各给一个反例或纠错点。",
                f"{knowledge_point} 常用方法/步骤是什么？",
                f"{knowledge_point} 的等价表述/充分必要条件有哪些？",
                f"{knowledge_point} 的边界情况/反例/不适用场景有哪些？",
                f"{knowledge_point} 的推导/证明思路（非细节）如何组织？",
            ]
            return tpl[:sub_n]

        # Best-effort cache for repeated searches inside a single (or continued) run.
        # Stored in working_memory so continuation tasks can reuse results without re-querying.
        try:
            cache_ttl_s = int(os.getenv("STUDY_MATERIALS_WEB_SEARCH_CACHE_TTL_S") or "3600")
        except Exception:
            cache_ttl_s = 3600
        cache_ttl_s = max(0, min(cache_ttl_s, 60 * 60 * 24))

        try:
            cache_max_entries = int(os.getenv("STUDY_MATERIALS_WEB_SEARCH_CACHE_MAX_ENTRIES") or "200")
        except Exception:
            cache_max_entries = 200
        cache_max_entries = max(0, min(cache_max_entries, 2000))

        cache = ctx.working_memory.get("_web_search_cache")
        if not isinstance(cache, dict):
            cache = {}
            ctx.working_memory["_web_search_cache"] = cache

        def _cache_key(payload: Dict[str, Any]) -> str:
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            return "ws1:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

        def _cache_get(key: str) -> Optional[Dict[str, Any]]:
            if not key:
                return None
            entry = cache.get(key)
            if not isinstance(entry, dict):
                return None
            try:
                ts = float(entry.get("ts_s") or 0.0)
            except Exception:
                ts = 0.0
            if cache_ttl_s and ts and (time.time() - ts) > float(cache_ttl_s):
                try:
                    cache.pop(key, None)
                except Exception:
                    pass
                return None
            value = entry.get("value")
            return dict(value) if isinstance(value, dict) else None

        def _cache_put(key: str, value: Dict[str, Any]) -> None:
            if not key:
                return
            if not isinstance(value, dict):
                return
            provider = str(value.get("provider") or "").strip().lower()
            results = value.get("results")
            # Cache only "successful enough" results; avoid caching empty failures for long.
            if provider in {"", "none"}:
                return
            if not (isinstance(results, list) and results):
                return

            cache[key] = {"ts_s": time.time(), "value": value}
            if cache_max_entries <= 0:
                return
            if len(cache) <= cache_max_entries:
                return
            try:
                items = sorted(
                    cache.items(),
                    key=lambda kv: float(kv[1].get("ts_s") or 0.0) if isinstance(kv[1], dict) else 0.0,
                )
                drop_n = max(0, len(items) - cache_max_entries)
                for k, _v in items[:drop_n]:
                    cache.pop(k, None)
            except Exception:
                for k in list(cache.keys())[: max(1, len(cache) - cache_max_entries)]:
                    cache.pop(k, None)

        async def _search_one_uncached(point: str) -> Dict[str, Any]:
            base_query = f"{subject} {point}".strip() if subject and subject not in point else point
            query = base_query
            if query_hint:
                query = f"{query} {query_hint}".strip()

            raw_search_mode = args.get("search_mode")
            if raw_search_mode is None:
                raw_search_mode = os.getenv("STUDY_MATERIALS_SEARCH_MODE")
            raw_search_mode = str(raw_search_mode or "").strip()
            force_search_mode = bool(raw_search_mode)

            search_mode = raw_search_mode.lower()
            if search_mode in {"deep", "research", "deepresearch"}:
                search_mode = "deepresearch"
            if not search_mode:
                search_mode = "deepresearch" if preset in {"deep", "research"} else "exa"

            if disable_metaso and search_mode == "metaso":
                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": [query],
                    "provider": "none",
                    "scope": scope,
                    "include_summary": include_summary,
                    "results": [],
                    "error": "metaso_disabled",
                }

            # 0) Exa Search (direct results). deepresearch => multi-round Exa search inspired by open-deep-research.
            if search_mode != "metaso":
                try:
                    from backend.mcp.exa_web_search import exa_search, EXA_API_KEY

                    if not EXA_API_KEY:
                        if force_search_mode:
                            return {
                                "knowledge_point": point,
                                "base_query": base_query,
                                "query": query,
                                "queries": [query],
                                "provider": "exa-deepresearch" if search_mode == "deepresearch" else "exa",
                                "scope": scope,
                                "include_summary": include_summary,
                                "results": [],
                                "error": "EXA_API_KEY not configured",
                            }
                    else:
                        keep_sources = _clamp_int(
                            args.get("keep_sources"),
                            default=_clamp_int(
                                os.getenv("STUDY_MATERIALS_WEB_KEEP_SOURCES") or limit,
                                default=limit,
                                min_value=3,
                                max_value=40,
                            ),
                            min_value=3,
                            max_value=40,
                        )

                        if search_mode == "deepresearch":
                            # Carry over previous calls (avoid repeating queries in multi-pass / multi-round research).
                            prev_item: Dict[str, Any] = {}
                            prev = ctx.working_memory.get("web_search_knowledge")
                            if isinstance(prev, dict):
                                if isinstance(prev.get("items"), list):
                                    for it in prev.get("items") or []:
                                        if not isinstance(it, dict):
                                            continue
                                        if str(it.get("knowledge_point") or "").strip() == point:
                                            prev_item = it
                                            break
                                elif str(prev.get("knowledge_point") or "").strip() == point:
                                    prev_item = prev

                            prev_queries = prev_item.get("queries") if isinstance(prev_item.get("queries"), list) else []
                            prev_summary = str(prev_item.get("summary") or "").strip()

                            thinking_model = str(
                                os.getenv("STUDY_MATERIALS_THINKING_MODEL")
                                or self.config.planner_model
                                or self.config.summarizer_model
                            ).strip()
                            llm_model = thinking_model if (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY) else ""

                            deep = await deep_research_exa(
                                call_llm_text=self._call_llm_text,
                                extract_json_obj=self._extract_json_obj,
                                strict_llm=strict_llm,
                                llm_model=llm_model,
                                knowledge_point=point,
                                subject=subject,
                                seed_query=query,
                                query_hint=query_hint,
                                preset=preset,
                                include_summary=include_summary,
                                text_max_length=text_max_length,
                                keep_sources=keep_sources,
                                breadth=args.get("deep_breadth") or os.getenv("STUDY_MATERIALS_DEEPRESEARCH_BREADTH"),
                                depth=args.get("deep_depth") or os.getenv("STUDY_MATERIALS_DEEPRESEARCH_DEPTH"),
                                max_queries=args.get("max_queries") or os.getenv("STUDY_MATERIALS_DEEPRESEARCH_MAX_QUERIES"),
                                per_query_results=args.get("per_query_results")
                                or os.getenv("STUDY_MATERIALS_DEEPRESEARCH_PER_QUERY_RESULTS"),
                                concurrency=args.get("deep_concurrency")
                                or os.getenv("STUDY_MATERIALS_DEEPRESEARCH_CONCURRENCY"),
                                learnings_per_query=args.get("learnings_per_query")
                                or os.getenv("STUDY_MATERIALS_DEEPRESEARCH_LEARNINGS_PER_QUERY"),
                                prev_queries=[str(x or "").strip() for x in prev_queries if str(x or "").strip()],
                                prev_summary=prev_summary,
                            )
                            if isinstance(deep, dict) and deep.get("success") and deep.get("results"):
                                results_value = deep.get("results") if isinstance(deep.get("results"), list) else []
                                out: Dict[str, Any] = {
                                    "knowledge_point": point,
                                    "base_query": base_query,
                                    "query": str(deep.get("query") or query or base_query).strip(),
                                    "queries": list(deep.get("queries") or [])[:40],
                                    "provider": str(deep.get("provider") or "exa-deepresearch"),
                                    "scope": scope,
                                    "include_summary": bool(
                                        deep.get("include_summary") if "include_summary" in deep else include_summary
                                    ),
                                    "summary": str(deep.get("summary") or "").strip(),
                                    "results": results_value[:keep_sources],
                                    "learnings": list(deep.get("learnings") or [])[:40],
                                    "directions": list(deep.get("directions") or [])[:12],
                                    "errors": list(deep.get("errors") or [])[:6],
                                    "depth": deep.get("depth"),
                                    "breadth": deep.get("breadth"),
                                    "max_queries": deep.get("max_queries"),
                                }
                                return {k: v for k, v in out.items() if v not in ("", None, [], {})}

                        # Decompose into sub-questions for better coverage
                        decompose = args.get("decompose")
                        if decompose is None:
                            decompose = _env_truthy("STUDY_MATERIALS_WEB_DECOMPOSE", True)
                        decompose = bool(decompose)

                        sub_questions = [query]
                        if decompose:
                            sub_questions = await _decompose_sub_questions(knowledge_point=point, base_query=base_query)
                            if query_hint:
                                # Ensure each sub query is nudged by the hint (when it isn't already included).
                                hinted: List[str] = []
                                hint_lower = query_hint.lower()
                                for sq in sub_questions:
                                    s = str(sq or "").strip()
                                    if not s:
                                        continue
                                    if hint_lower and hint_lower in s.lower():
                                        hinted.append(s)
                                    else:
                                        hinted.append(f"{s} {query_hint}".strip())
                                sub_questions = hinted or sub_questions

                        per_query_results = _clamp_int(
                            args.get("per_query_results"),
                            default=_clamp_int(
                                os.getenv("STUDY_MATERIALS_EXA_PER_QUERY_RESULTS") or min(5, limit),
                                default=min(5, limit),
                                min_value=2,
                                max_value=10,
                            ),
                            min_value=1,
                            max_value=10,
                        )

                        # Ask Exa for each sub-question
                        sub_conc = _clamp_int(
                            args.get("sub_concurrency"),
                            default=_clamp_int(os.getenv("STUDY_MATERIALS_WEB_SUBQUERY_CONCURRENCY") or 2, default=2, min_value=1, max_value=4),
                            min_value=1,
                            max_value=4,
                        )
                        sub_sem = asyncio.Semaphore(sub_conc)

                        async def _exa_ask_one(sub_q: str) -> Dict[str, Any]:
                            async with sub_sem:
                                return await exa_search(
                                    query=sub_q,
                                    num_results=min(per_query_results, 10),
                                    use_autoprompt=True,
                                    type="neural",
                                    include_text=True,
                                    text_max_length=min(text_max_length, 2600),
                                )

                        exa_calls = await asyncio.gather(*[_exa_ask_one(q) for q in sub_questions])

                        cleaned_results: List[Dict[str, Any]] = []
                        summary_parts: List[str] = []
                        errors: List[str] = []
                        queries: List[str] = []

                        for sub_q, res in zip(sub_questions, exa_calls):
                            queries.append(sub_q)

                            raw_results = res.get("results") if isinstance(res, dict) else []
                            if not isinstance(raw_results, list) or not raw_results:
                                err = (
                                    str(res.get("error") or "exa search failed").strip()
                                    if isinstance(res, dict)
                                    else "exa search failed"
                                )
                                errors.append(f"{sub_q}: {err}")
                                continue

                            this_results: List[Dict[str, Any]] = []
                            for r in raw_results:
                                if not isinstance(r, dict):
                                    continue
                                rr = dict(r)
                                rr.setdefault("source_query", sub_q)
                                pr = _postprocess_web_search_result(rr)
                                cleaned_results.append(pr)
                                this_results.append(pr)

                            if include_summary and this_results:
                                top_snips: List[str] = []
                                for r in this_results[:2]:
                                    title = str(r.get("title") or "").strip()
                                    snip = str(r.get("snippet") or "").strip()
                                    if title and snip:
                                        top_snips.append(f"- {title}：{_clip_text(snip, max_chars=180)}")
                                if top_snips:
                                    summary_parts.append(f"【{sub_q}】\n" + "\n".join(top_snips))

                        # Deduplicate results by URL.
                        deduped: List[Dict[str, Any]] = []
                        seen_urls: set[str] = set()
                        for r in cleaned_results:
                            url_value = str(r.get("url") or "").strip()
                            key = url_value or json.dumps(r, ensure_ascii=False, sort_keys=True)
                            if key in seen_urls:
                                continue
                            seen_urls.add(key)
                            deduped.append(r)
                            if len(deduped) >= keep_sources:
                                 break

                        summary_value = "\n\n".join(summary_parts).strip() if include_summary else ""

                        # If we got useful results, return them
                        if summary_value or deduped:
                            out = {
                                "knowledge_point": point,
                                "base_query": base_query,
                                "query": query,
                                "queries": queries[:12],
                                "provider": "exa-search+decompose" if decompose else "exa-search",
                                "scope": scope,
                                "include_summary": include_summary,
                                "summary": summary_value,
                                "results": deduped,
                                "sub_questions": sub_questions,
                                "errors": errors[:6],
                            }
                            return {k: v for k, v in out.items() if v not in ("", None, [], {})}

                        # If Exa failed completely, fall through to Metaso
                        if errors:
                            if force_search_mode:
                                return {
                                    "knowledge_point": point,
                                    "base_query": base_query,
                                    "query": query,
                                    "queries": queries[:12],
                                    "provider": "exa-search+decompose" if decompose else "exa-search",
                                    "scope": scope,
                                    "include_summary": include_summary,
                                    "results": [],
                                    "errors": errors[:6],
                                    "error": "exa_search_failed",
                                }

                            if not disable_metaso:
                                print(
                                    f"[web_search] Exa search failed for {point}, falling back to Metaso: {errors[:2]}",
                                    flush=True,
                                )
                except Exception as exc:
                    if force_search_mode:
                        return {
                            "knowledge_point": point,
                            "base_query": base_query,
                            "query": query,
                            "queries": [query],
                            "provider": "exa-deepresearch" if search_mode == "deepresearch" else "exa",
                            "scope": scope,
                            "include_summary": include_summary,
                            "results": [],
                            "error": str(exc) or "exa_search_exception",
                        }
                    if not disable_metaso:
                        print(f"[web_search] Exa search exception for {point}, falling back to Metaso: {exc}", flush=True)

            metaso: Dict[str, Any] = {}
            if not disable_metaso:
                metaso_mode = str(args.get("metaso_mode") or os.getenv("STUDY_MATERIALS_METASO_MODE") or "ask").strip().lower()
                if metaso_mode not in {"ask", "search"}:
                    metaso_mode = "ask"

                # 1) Metaso（fallback when Exa not configured or failed）
                if metaso_mode == "ask":
                    # Sub-agent behavior: decompose the knowledge point into smaller questions, then ask.
                    decompose = args.get("decompose")
                    if decompose is None:
                        decompose = _env_truthy("STUDY_MATERIALS_WEB_DECOMPOSE", True)
                    decompose = bool(decompose)

                    # How many sources to keep overall (not per sub-question)
                    keep_sources = _clamp_int(
                        args.get("keep_sources"),
                        default=_clamp_int(
                            os.getenv("STUDY_MATERIALS_WEB_KEEP_SOURCES") or limit,
                            default=limit,
                            min_value=3,
                            max_value=40,
                        ),
                        min_value=3,
                        max_value=40,
                    )

                    # Per-sub-question size: keep small because we ask multiple times.
                    sub_size = _clamp_int(
                        args.get("sub_size"),
                        default=_clamp_int(
                            os.getenv("STUDY_MATERIALS_WEB_SUBQUERY_SIZE") or min(5, limit),
                            default=min(5, limit),
                            min_value=2,
                            max_value=10,
                        ),
                        min_value=2,
                        max_value=10,
                    )

                    metaso_format = str(args.get("metaso_format") or os.getenv("METASO_ASK_FORMAT") or "simple")
                    metaso_model = str(args.get("metaso_model") or os.getenv("METASO_ASK_MODEL") or "")

                    sub_questions = [base_query]
                    if decompose:
                        sub_questions = await _decompose_sub_questions(knowledge_point=point, base_query=base_query)

                    # Ask Metaso for each sub-question; cap concurrency to avoid rate-limits.
                    sub_conc = _clamp_int(
                        args.get("sub_concurrency"),
                        default=_clamp_int(
                            os.getenv("STUDY_MATERIALS_WEB_SUBQUERY_CONCURRENCY") or 2,
                            default=2,
                            min_value=1,
                            max_value=3,
                        ),
                        min_value=1,
                        max_value=3,
                    )
                    sub_sem = asyncio.Semaphore(sub_conc)

                    async def _ask_one(sub_q: str) -> Dict[str, Any]:
                        # Important: we treat Metaso as *retrieval + research notes* here, not the final writer.
                        # If we ask Metaso to write long paragraphs, downstream LLMs tend to copy them verbatim.
                        prompt_lines = [
                            "你是自学资料的研究助理。请输出“可用于写教材的研究笔记”，而不是直接写教材正文。",
                            "输出要求：",
                            "1) 中文；分小节输出：定义/符号约定、直观理解、关键结论(含适用条件)、常见误区(含纠正要点或反例提示)、常用方法/解题套路、关键词/同义词(可含英文/符号)。",
                            "2) 尽量用要点列表；避免长段落；单条建议 ≤ 40 字。",
                            "3) 不要输出网址/链接；不要输出 [[1]] 这类证据标记；不要输出过程性叙述(如“根据搜索/证据/资料”).",
                            "4) 不确定处请标注“可能/待核实”，不要编造。",
                            "5)（研究型）尽量写清：适用条件/边界情况/反例提示；如存在等价表述/充分必要条件请指出。"
                            if preset in {"deep", "research"}
                            else "5) 尽量写清适用条件与限制条件。",
                            "6)（研究型）若适用，请补充 3~8 行推导/证明骨架（不是完整证明）。"
                            if preset == "research"
                            else "",
                            f"知识点：{base_query}",
                            f"子问题：{sub_q}",
                        ]
                        if query_hint:
                            prompt_lines.append(f"关注要点（关键词）：{query_hint}")
                        metaso_q = "\n".join(prompt_lines).strip()

                        async with sub_sem:
                            return await metaso_ask(
                                query=metaso_q,
                                scope=scope,
                                size=sub_size,
                                format=metaso_format,
                                model=metaso_model,
                            )

                    metaso_calls = await asyncio.gather(*[_ask_one(q) for q in sub_questions])

                    cleaned_results: List[Dict[str, Any]] = []
                    summary_parts: List[str] = []
                    errors: List[str] = []
                    queries: List[str] = []

                    for sub_q, res in zip(sub_questions, metaso_calls):
                        # Track queries for observability/merging.
                        queries.append(sub_q)

                        if not isinstance(res, dict) or not res.get("success"):
                            err = (
                                str(res.get("error") or "metaso ask failed").strip()
                                if isinstance(res, dict)
                                else "metaso ask failed"
                            )
                            errors.append(f"{sub_q}: {err}")
                            continue

                        ans = _clean_metaso_answer(str(res.get("answer") or "").strip())
                        if include_summary and ans:
                            # Keep each block compact; downstream will still do its own LLM writing.
                            summary_parts.append(f"【{sub_q}】\n{_clip_text(ans, max_chars=900)}")

                        for r in (res.get("results") or []):
                            if not isinstance(r, dict):
                                continue
                            cleaned_results.append(_postprocess_web_search_result(r))

                    # Deduplicate results by URL and keep bounded.
                    deduped: List[Dict[str, Any]] = []
                    seen_urls: set[str] = set()
                    for r in cleaned_results:
                        url_value = str(r.get("url") or "").strip()
                        key = url_value or json.dumps(r, ensure_ascii=False, sort_keys=True)
                        if key in seen_urls:
                            continue
                        seen_urls.add(key)
                        deduped.append(r)
                        if len(deduped) >= keep_sources:
                            break

                    summary_value = "\n\n".join(summary_parts).strip() if include_summary else ""
                    if include_summary and not summary_value and errors:
                        summary_value = "（Metaso /ask 未返回可用内容：" + "; ".join(errors[:2]) + "）"

                    out = {
                        "knowledge_point": point,
                        "base_query": base_query,
                        "query": base_query,
                        "queries": queries[:12],
                        "provider": "metaso-ask+decompose" if decompose else "metaso-ask",
                        "scope": scope,
                        "include_summary": include_summary,
                        "summary": summary_value,
                        "results": deduped,
                        "sub_questions": sub_questions,
                        "errors": errors[:6],
                    }
                    return {k: v for k, v in out.items() if v not in ("", None, [], {})}

                # metaso_mode == "search"
                metaso = await metaso_search(query=query, scope=scope, include_summary=include_summary, size=limit)

                if isinstance(metaso, dict) and metaso.get("success"):
                    cleaned_results: List[Dict[str, Any]] = []
                    for r in (metaso.get("results") or []):
                        if not isinstance(r, dict):
                            continue
                        cleaned_results.append(_postprocess_web_search_result(r))
                    cleaned_results = cleaned_results[: max(1, limit)]

                    summary_value = str(metaso.get("summary") or "").strip()

                    return {
                        "knowledge_point": point,
                        "base_query": base_query,
                        "query": query,
                        "queries": [query],
                        "provider": "metaso",
                        "scope": scope,
                        "include_summary": include_summary,
                        "summary": summary_value,
                        "results": cleaned_results,
                    }

            # 2) Legacy fallback：Exa -> BigModel MCP broker（best-effort）
            try:
                from backend.mcp.exa_web_search import exa_search
                from backend.mcp.bigmodel_web_search import web_search_with_bigmodel_mcp

                exa = await exa_search(
                    query=query,
                    num_results=limit,
                    use_autoprompt=True,
                    type="neural",
                    include_text=True,
                    text_max_length=text_max_length,
                )
                exa_results = exa.get("results") if isinstance(exa, dict) else []
                if isinstance(exa_results, list) and exa_results:
                    cleaned_results: List[Dict[str, Any]] = []
                    for r in exa_results:
                        if not isinstance(r, dict):
                            continue
                        cleaned_results.append(_postprocess_web_search_result(r))
                    return {
                        "knowledge_point": point,
                        "base_query": base_query,
                        "query": query,
                        "queries": [query],
                        "provider": "exa",
                        "results": cleaned_results,
                        "autoprompt_string": exa.get("autoprompt_string") if isinstance(exa, dict) else None,
                        "error": str(metaso.get("error") or "").strip() if isinstance(metaso, dict) else "",
                    }

                zhipu = await web_search_with_bigmodel_mcp(query=query, limit=limit)
                if isinstance(zhipu, dict) and zhipu.get("success") and zhipu.get("results"):
                    cleaned_results = []
                    for r in (zhipu.get("results") or []):
                        if not isinstance(r, dict):
                            continue
                        cleaned_results.append(_postprocess_web_search_result(r))
                    return {
                        "knowledge_point": point,
                        "base_query": base_query,
                        "query": query,
                        "queries": [query],
                        "provider": str(zhipu.get("provider") or "zhipu-bigmodel-mcp-web-search"),
                        "results": cleaned_results,
                        "error": str(metaso.get("error") or "").strip() if isinstance(metaso, dict) else "",
                    }

                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": [query],
                    "provider": "none",
                    "results": [],
                    "error": str(metaso.get("error") or "web search failed").strip()
                    if isinstance(metaso, dict)
                    else "web search failed",
                }
            except Exception as exc:  # pragma: no cover
                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": [query],
                    "provider": "none",
                    "results": [],
                    "error": str(exc) or "web search failed",
                }

        async def _search_one(point: str) -> Dict[str, Any]:
            base_query = f"{subject} {point}".strip() if subject and subject not in point else point
            query = base_query
            if query_hint:
                query = f"{query} {query_hint}".strip()

            raw_search_mode = args.get("search_mode")
            if raw_search_mode is None:
                raw_search_mode = os.getenv("STUDY_MATERIALS_SEARCH_MODE")
            raw_search_mode = str(raw_search_mode or "").strip()
            search_mode_key = raw_search_mode.lower()
            if search_mode_key in {"deep", "research", "deepresearch"}:
                search_mode_key = "deepresearch"
            if not search_mode_key:
                search_mode_key = "deepresearch" if preset in {"deep", "research"} else "exa"

            key = _cache_key(
                {
                    "mode": search_mode_key,
                    "query": query,
                    "scope": scope,
                    "include_summary": include_summary,
                    "limit": limit,
                    "text_max_length": text_max_length,
                }
            )
            cached = _cache_get(key)
            if cached:
                cached["knowledge_point"] = point
                cached["base_query"] = base_query
                cached["query"] = query
                cached["cache_hit"] = True
                return cached

            res = await _search_one_uncached(point)
            try:
                _cache_put(key, res)
            except Exception:
                pass
            return res

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _search_one(point)
                except Exception as exc:  # pragma: no cover
                    return {
                        "knowledge_point": point,
                        "query": point,
                        "provider": "none",
                        "results": [],
                        "error": str(exc),
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "limit": limit,
            "query_hint": query_hint,
            "scope": scope,
            "include_summary": include_summary,
            "text_max_length": text_max_length,
            "items": items,
        }
