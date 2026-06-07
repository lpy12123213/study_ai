"""Implementation module for the `web_search_knowledge` tool.

The stable import path is `backend.agent.tools.search.web_search_knowledge`.
Keep heavy logic here; the public module re-exports the mixin.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.agent.tools.search.deep_research import deep_research
from backend.agent.tools.utils.text_utils import _clip_text, _postprocess_web_search_result
from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.core.settings import STUDY_MATERIALS_THINKING_MODEL
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry

logger = get_logger(__name__)


def _web_subquestion_system_prompt() -> str:
    return create_default_prompt_registry().render("search.web_subquestion.decompose.v1").content


class WebSearchKnowledgeToolsMixin:
    async def _tool_web_search_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """网络搜索知识点（Tavily 优先，可选 deepresearch 多轮；Exa/Metaso/智谱兜底）。

        - search_mode=deepresearch：多轮检索（Tavily 优先，回退 Exa）+ 学习要点/追问方向
        - search_mode=tavily：Tavily 直接搜索（可选拆分子问题）
        - search_mode=exa：Exa 直接搜索（可选拆分子问题）
        - search_mode=metaso：强制使用 Metaso（ask/search），跳过 Tavily/Exa
        - 注意：当显式设置 search_mode 时，失败不会自动回退到其他供应商
        - disable_metaso=true 或 STUDY_MATERIALS_DISABLE_METASO=1：禁用 Metaso（含兜底）
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        limit = int(args.get("limit") or 5)
        # Allow more per-knowledge-point calls when the user enables deeper presets; keep a safe upper bound.
        limit = max(1, min(limit, 25))
        query_hint = str(args.get("query_hint") or "").strip()
        scope = str(args.get("scope") or "webpage").strip() or "webpage"
        include_summary_raw = args.get("include_summary")
        if include_summary_raw is None:
            include_summary = False
        elif isinstance(include_summary_raw, bool):
            include_summary = include_summary_raw
        else:
            include_summary = str(include_summary_raw).strip().lower() in {"1", "true", "yes", "y", "on"}
        text_max_length = int(args.get("text_max_length") or 2600)
        text_max_length = max(200, min(text_max_length, 8000))
        strict_llm = self._strict_llm(ctx, args)
        if strict_llm and not is_llm_configured():
            raise RuntimeError("llm_not_configured")

        # Study preset helps SubAgent choose better sub-questions and prompt style.
        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        preset = (
            str(args.get("preset") or study_opts.get("preset") or os.getenv("STUDY_MATERIALS_PRESET") or "")
            .strip()
            .lower()
        )
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

        from backend.integrations.mcp.search.metaso import metaso_ask, metaso_search

        def _env_truthy(name: str, default: bool = False) -> bool:
            raw = (os.getenv(name) or "").strip().lower()
            if not raw:
                return default
            return raw in {"1", "true", "yes", "y", "on"}

        def _normalize_result(r: Dict[str, Any], *, provider: str, source_query: str) -> Dict[str, Any]:
            rr = dict(r or {})
            if source_query:
                rr.setdefault("source_query", source_query)
            pr = _postprocess_web_search_result(rr)
            if provider:
                pr.setdefault("provider", provider)
            return pr

        disable_metaso_raw = args.get("disable_metaso")
        if disable_metaso_raw is None:
            disable_metaso = _env_truthy("STUDY_MATERIALS_DISABLE_METASO", False)
        else:
            disable_metaso = str(disable_metaso_raw).strip().lower() in {"1", "true", "yes", "y", "on"}

        def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
            try:
                n = int(value)
            except (TypeError, ValueError):
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
                STUDY_MATERIALS_THINKING_MODEL or self.config.planner_model or self.config.summarizer_model
            ).strip()

            sub_n = _clamp_int(
                args.get("sub_questions"),
                default=_clamp_int(
                    os.getenv("STUDY_MATERIALS_WEB_SUBQUERIES") or 4, default=4, min_value=2, max_value=25
                ),
                min_value=2,
                max_value=25,
            )

            # If LLM isn't configured, fall back to a deterministic template split (non-strict only).
            if not is_llm_configured():
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
                    f"Split the knowledge point into {sub_n} sub-questions suitable for a web Q&A API. Each sub-question must be one sentence.",
                    "子问题要覆盖：定义/直观理解/关键结论与条件/常见误区/方法步骤（可合并，但要覆盖）。",
                    "尽量包含：等价表述/充分必要条件、边界情况/反例、不适用条件、与相近概念的区别（若适用）。"
                    if preset in {"deep", "research"}
                    else "（可选）如存在等价表述/边界情况/反例，也可作为子问题的一部分。",
                    "尽量包含：推导/证明思路的“骨架”（若适用）。"
                    if preset in {"deep", "research"}
                    else "（可选）需要时可补充推导/证明思路。",
                    "子问题要足够具体，避免泛泛而谈；每个子问题尽量能检索到不同角度的资料。",
                    "Output strict JSON only. Do not output explanatory text.",
                ],
                "output_schema": {"sub_questions": ["string"]},
            }

            last_err = ""
            for attempt in range(3):
                text = await self._call_llm_text(
                    messages=[
                        {"role": "system", "content": _web_subquestion_system_prompt()},
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
        except (TypeError, ValueError):
            cache_ttl_s = 3600
        cache_ttl_s = max(0, min(cache_ttl_s, 60 * 60 * 24))

        try:
            cache_max_entries = int(os.getenv("STUDY_MATERIALS_WEB_SEARCH_CACHE_MAX_ENTRIES") or "200")
        except (TypeError, ValueError):
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
            except (TypeError, ValueError):
                ts = 0.0
            if cache_ttl_s and ts and (time.time() - ts) > float(cache_ttl_s):
                try:
                    cache.pop(key, None)
                except Exception:
                    logger.warning("web_search_cache_evict_failed", extra={"key": key}, exc_info=True)
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
                logger.warning("web_search_cache_prune_failed", exc_info=True)
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
                search_mode = "deepresearch" if preset in {"deep", "research"} else "tavily"

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

            def _provider_error(provider: str, error: str, *, errors: Optional[List[str]] = None) -> Dict[str, Any]:
                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": [query],
                    "provider": provider,
                    "scope": scope,
                    "include_summary": include_summary,
                    "results": [],
                    "errors": (errors or [])[:6],
                    "error": error,
                }

            def _previous_research_state() -> tuple[List[str], str]:
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
                clean_queries = [str(x or "").strip() for x in prev_queries if str(x or "").strip()]
                prev_summary = str(prev_item.get("summary") or "").strip()
                return clean_queries, prev_summary

            def _format_deep_research_output(deep: Dict[str, Any], *, provider_value: str) -> Dict[str, Any]:
                query_value = str(deep.get("query") or query or base_query).strip()
                results_value = deep.get("results") if isinstance(deep.get("results"), list) else []
                cleaned_results: List[Dict[str, Any]] = []
                for r in results_value:
                    if not isinstance(r, dict):
                        continue
                    cleaned_results.append(
                        _normalize_result(
                            r,
                            provider=provider_value,
                            source_query=str(r.get("source_query") or query_value).strip(),
                        )
                    )
                out: Dict[str, Any] = {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query_value,
                    "queries": list(deep.get("queries") or [])[:40],
                    "provider": provider_value,
                    "scope": scope,
                    "include_summary": bool(
                        deep.get("include_summary") if "include_summary" in deep else include_summary
                    ),
                    "summary": str(deep.get("summary") or "").strip(),
                    "results": cleaned_results[:keep_sources],
                    "learnings": list(deep.get("learnings") or [])[:40],
                    "directions": list(deep.get("directions") or [])[:12],
                    "errors": list(deep.get("errors") or [])[:6],
                    "depth": deep.get("depth"),
                    "breadth": deep.get("breadth"),
                    "max_queries": deep.get("max_queries"),
                }
                return {k: v for k, v in out.items() if v not in ("", None, [], {})}

            async def _run_deep_research_with_provider(
                *,
                provider_value: str,
                search_func: Callable[[str, int], Awaitable[Dict[str, Any]]],
            ) -> Dict[str, Any]:
                prev_queries, prev_summary = _previous_research_state()
                thinking_model = str(
                    STUDY_MATERIALS_THINKING_MODEL or self.config.planner_model or self.config.summarizer_model
                ).strip()
                llm_model = thinking_model if is_llm_configured() else ""

                deep = await deep_research(
                    call_llm_text=self._call_llm_text,
                    extract_json_obj=self._extract_json_obj,
                    strict_llm=strict_llm,
                    llm_model=llm_model,
                    knowledge_point=point,
                    subject=subject,
                    seed_query=query,
                    search_func=search_func,
                    search_provider_name=provider_value,
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
                    prev_queries=prev_queries,
                    prev_summary=prev_summary,
                )
                if isinstance(deep, dict) and deep.get("success") and deep.get("results"):
                    return _format_deep_research_output(deep, provider_value=str(deep.get("provider") or provider_value))
                return _provider_error(
                    provider_value,
                    str((deep or {}).get("error") or f"{provider_value}_failed"),
                    errors=list((deep or {}).get("errors") or []) if isinstance(deep, dict) else [],
                )

            async def _run_direct_search_with_provider(
                *,
                provider_base: str,
                per_query_env: str,
                default_error: str,
                search_one: Callable[[str, int], Awaitable[Dict[str, Any]]],
            ) -> Dict[str, Any]:
                decompose = args.get("decompose")
                if decompose is None:
                    decompose = _env_truthy("STUDY_MATERIALS_WEB_DECOMPOSE", True)
                decompose = bool(decompose)
                provider_value = f"{provider_base}+decompose" if decompose else provider_base

                sub_questions = [query]
                if decompose:
                    sub_questions = await _decompose_sub_questions(knowledge_point=point, base_query=base_query)
                    if query_hint:
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
                        os.getenv(per_query_env) or min(5, limit),
                        default=min(5, limit),
                        min_value=2,
                        max_value=10,
                    ),
                    min_value=1,
                    max_value=10,
                )

                sub_conc = _clamp_int(
                    args.get("sub_concurrency"),
                    default=_clamp_int(
                        os.getenv("STUDY_MATERIALS_WEB_SUBQUERY_CONCURRENCY") or 2,
                        default=2,
                        min_value=1,
                        max_value=4,
                    ),
                    min_value=1,
                    max_value=4,
                )
                sub_sem = asyncio.Semaphore(sub_conc)

                async def _ask_one(sub_q: str) -> Dict[str, Any]:
                    async with sub_sem:
                        return await search_one(sub_q, per_query_results)

                calls = await asyncio.gather(*[_ask_one(q) for q in sub_questions])

                cleaned_results: List[Dict[str, Any]] = []
                summary_parts: List[str] = []
                errors: List[str] = []
                queries: List[str] = []

                for sub_q, res in zip(sub_questions, calls):
                    queries.append(sub_q)

                    raw_results = res.get("results") if isinstance(res, dict) else []
                    if not isinstance(raw_results, list) or not raw_results:
                        err = (
                            str(res.get("error") or default_error).strip()
                            if isinstance(res, dict)
                            else default_error
                        )
                        errors.append(f"{sub_q}: {err}")
                        continue

                    this_results: List[Dict[str, Any]] = []
                    for r in raw_results:
                        if not isinstance(r, dict):
                            continue
                        pr = _normalize_result(r, provider=provider_value, source_query=sub_q)
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
                out = {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": queries[:12],
                    "provider": provider_value,
                    "scope": scope,
                    "include_summary": include_summary,
                    "summary": summary_value,
                    "results": deduped,
                    "sub_questions": sub_questions,
                    "errors": errors[:6],
                }
                if summary_value or deduped:
                    return {k: v for k, v in out.items() if v not in ("", None, [], {})}

                out["error"] = provider_base.replace("-", "_") + "_failed"
                return {k: v for k, v in out.items() if v not in ("", None, [], {})}

            # 0) Tavily Search (default) / Exa fallback. deepresearch uses the same multi-round engine.
            if search_mode != "metaso":
                provider_errors: List[str] = []

                if search_mode in {"tavily", "deepresearch"}:
                    try:
                        from backend.integrations.mcp.search.tavily import TAVILY_API_KEY, tavily_search

                        if not TAVILY_API_KEY:
                            tavily_missing = "TAVILY_API_KEY not configured"
                            provider_errors.append(tavily_missing)
                            if force_search_mode and search_mode == "tavily":
                                return _provider_error("tavily-search", tavily_missing)
                        elif search_mode == "deepresearch":

                            async def _tavily_deep_search(q: str, num_results: int) -> Dict[str, Any]:
                                return await tavily_search(
                                    query=q,
                                    max_results=min(num_results, 10),
                                    search_depth="advanced",
                                    include_answer=False,
                                    include_raw_content=True,
                                )

                            tavily_deep = await _run_deep_research_with_provider(
                                provider_value="tavily-deepresearch",
                                search_func=_tavily_deep_search,
                            )
                            if tavily_deep.get("results"):
                                return tavily_deep
                            provider_errors.append(str(tavily_deep.get("error") or "tavily_deepresearch_failed"))
                        else:

                            async def _tavily_ask_one(sub_q: str, per_query_results: int) -> Dict[str, Any]:
                                return await tavily_search(
                                    query=sub_q,
                                    max_results=min(per_query_results, 10),
                                    search_depth="basic",
                                    include_answer=False,
                                    include_raw_content=True,
                                )

                            tavily_direct = await _run_direct_search_with_provider(
                                provider_base="tavily-search",
                                per_query_env="STUDY_MATERIALS_TAVILY_PER_QUERY_RESULTS",
                                default_error="tavily search failed",
                                search_one=_tavily_ask_one,
                            )
                            if tavily_direct.get("results"):
                                return tavily_direct
                            provider_errors.append(str(tavily_direct.get("error") or "tavily_search_failed"))
                            if force_search_mode:
                                return tavily_direct
                    except Exception as exc:
                        provider_errors.append(str(exc) or "tavily_search_exception")
                        if force_search_mode and search_mode == "tavily":
                            return _provider_error("tavily-search", str(exc) or "tavily_search_exception")
                        logger.warning(
                            "Tavily search failed; falling back",
                            extra={"knowledge_point": point, "error": str(exc)},
                            exc_info=True,
                        )

                try:
                    from backend.integrations.mcp.search.exa import EXA_API_KEY, exa_search

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
                        if search_mode == "deepresearch":
                            async def _exa_deep_search(q: str, num_results: int) -> Dict[str, Any]:
                                return await exa_search(
                                    query=q,
                                    num_results=min(num_results, 10),
                                    use_autoprompt=True,
                                    type="neural",
                                    include_text=True,
                                    text_max_length=min(text_max_length, 2600),
                                )

                            exa_deep = await _run_deep_research_with_provider(
                                provider_value="exa-deepresearch",
                                search_func=_exa_deep_search,
                            )
                            if exa_deep.get("results"):
                                return exa_deep
                            provider_errors.append(str(exa_deep.get("error") or "exa_deepresearch_failed"))
                            if force_search_mode:
                                return exa_deep
                        elif search_mode in {"tavily", "exa"}:

                            async def _exa_ask_one(sub_q: str, per_query_results: int) -> Dict[str, Any]:
                                return await exa_search(
                                    query=sub_q,
                                    num_results=min(per_query_results, 10),
                                    use_autoprompt=True,
                                    type="neural",
                                    include_text=True,
                                    text_max_length=min(text_max_length, 2600),
                                )

                            exa_direct = await _run_direct_search_with_provider(
                                provider_base="exa-search",
                                per_query_env="STUDY_MATERIALS_EXA_PER_QUERY_RESULTS",
                                default_error="exa search failed",
                                search_one=_exa_ask_one,
                            )
                            if exa_direct.get("results"):
                                return exa_direct
                            provider_errors.append(str(exa_direct.get("error") or "exa_search_failed"))
                            if force_search_mode:
                                return exa_direct
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
                        logger.warning(
                            "Exa search exception; falling back to Metaso",
                            extra={"knowledge_point": point, "error": str(exc)},
                            exc_info=True,
                        )

                if force_search_mode and search_mode == "deepresearch":
                    return _provider_error("deepresearch", "; ".join(provider_errors) or "deepresearch_failed")

            metaso: Dict[str, Any] = {}
            if not disable_metaso:
                metaso_mode = (
                    str(args.get("metaso_mode") or os.getenv("STUDY_MATERIALS_METASO_MODE") or "ask").strip().lower()
                )
                if metaso_mode not in {"ask", "search"}:
                    metaso_mode = "ask"

                # 1) Metaso（fallback when Exa not configured or failed）
                if metaso_mode == "ask":
                    # Sub-agent behavior: decompose the knowledge point into smaller questions, then ask.
                    decompose = args.get("decompose")
                    if decompose is None:
                        decompose = _env_truthy("STUDY_MATERIALS_WEB_DECOMPOSE", True)
                    decompose = bool(decompose)
                    provider_value = "metaso-ask+decompose" if decompose else "metaso-ask"

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
                            "You are a research assistant for self-study material. Output research notes usable for writing educational material, not the final textbook prose.",
                            "Output requirements:",
                            "1) Match the user's/topic language. Organize into sections: definitions/notation, intuition, key conclusions including conditions, common misconceptions with corrections or counterexample hints, common methods or solution routines, keywords/synonyms including English or symbols when useful.",
                            "2) 尽量用要点列表；避免长段落；单条建议 ≤ 40 字。",
                            "3) Do not output URLs or links. Do not output evidence markers such as [[1]]. Do not output process narration such as 'according to search/evidence/material'.",
                            "4) Mark uncertain points as possible/to be verified in the user's language. Do not fabricate.",
                            "5) For research-oriented output, state conditions of use, boundary cases, and counterexample hints when possible. Point out equivalent statements or necessary/sufficient conditions when they exist."
                            if preset in {"deep", "research"}
                            else "5) 尽量写清适用条件与限制条件。",
                            "6) For research-oriented output, add a 3-8 line derivation/proof skeleton when applicable. Do not write a full proof."
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

                        for r in res.get("results") or []:
                            if not isinstance(r, dict):
                                continue
                            cleaned_results.append(_normalize_result(r, provider=provider_value, source_query=sub_q))

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
                        "provider": provider_value,
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
                    for r in metaso.get("results") or []:
                        if not isinstance(r, dict):
                            continue
                        cleaned_results.append(_normalize_result(r, provider="metaso", source_query=query))
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

            # 2) BigModel MCP fallback (best-effort).
            try:
                from backend.integrations.mcp.search.bigmodel import web_search_with_bigmodel_mcp

                zhipu = await web_search_with_bigmodel_mcp(query=query, limit=limit)
                if isinstance(zhipu, dict) and zhipu.get("success") and zhipu.get("results"):
                    provider_value = str(zhipu.get("provider") or "zhipu-bigmodel-mcp-web-search")
                    cleaned_results: List[Dict[str, Any]] = []
                    for r in zhipu.get("results") or []:
                        if not isinstance(r, dict):
                            continue
                        cleaned_results.append(_normalize_result(r, provider=provider_value, source_query=query))
                    return {
                        "knowledge_point": point,
                        "base_query": base_query,
                        "query": query,
                        "queries": [query],
                        "provider": provider_value,
                        "scope": scope,
                        "include_summary": include_summary,
                        "results": cleaned_results[: max(1, limit)],
                        "error": str(metaso.get("error") or "").strip() if isinstance(metaso, dict) else "",
                    }

                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": [query],
                    "provider": "none",
                    "scope": scope,
                    "include_summary": include_summary,
                    "results": [],
                    "error": str(metaso.get("error") or "web search failed").strip()
                    if isinstance(metaso, dict)
                    else "web search failed",
                }
            except Exception as exc:  # pragma: no cover
                logger.warning("BigModel search failed", extra={"knowledge_point": point, "error": str(exc)}, exc_info=True)
                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": [query],
                    "provider": "none",
                    "scope": scope,
                    "include_summary": include_summary,
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
                search_mode_key = "deepresearch" if preset in {"deep", "research"} else "tavily"

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
                logger.warning("web_search_cache_put_failed", extra={"key": key}, exc_info=True)
            return res

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _search_one(point)
                except Exception as exc:  # pragma: no cover
                    logger.warning("web_search_knowledge_point_failed", extra={"point": point}, exc_info=True)
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
