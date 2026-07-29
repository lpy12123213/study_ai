from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from backend.agent.tools.utils.text_utils import _clip_text, _postprocess_web_search_result
from backend.llm.prompts import create_default_prompt_registry

CallLLMText = Callable[..., Awaitable[str]]
ExtractJsonObj = Callable[[str], Dict[str, Any]]
SearchFunc = Callable[[str, int], Awaitable[Dict[str, Any]]]


def _search_strategy_system_prompt() -> str:
    return create_default_prompt_registry().render("search.deep_research.strategy.v1").content


def _learning_extraction_system_prompt() -> str:
    return create_default_prompt_registry().render("search.deep_research.learning_extraction.v1").content


def _dedup_strings(items: List[str], *, keep: int) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for it in items or []:
        s = str(it or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= keep:
            break
    return out


def _dedup_results(results: List[Dict[str, Any]], *, keep: int) -> List[Dict[str, Any]]:
    keep = max(1, int(keep or 0))
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for r in results or []:
        if not isinstance(r, dict):
            continue
        url_value = str(r.get("url") or "").strip()
        key = url_value.lower() if url_value else ""
        if not key:
            try:
                key = json.dumps(r, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= keep:
            break
    return out


def deepresearch_defaults(preset: str) -> Tuple[int, int, int]:
    preset = str(preset or "").strip().lower()
    if preset == "research":
        return (6, 3, 24)  # breadth, depth, max_queries
    if preset == "deep":
        return (4, 2, 16)
    if preset == "quick":
        return (2, 1, 4)
    # standard / unknown
    return (3, 1, 6)


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    n = _as_int(value, default=default)
    return max(min_value, min(max_value, n))


def _norm_query(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


async def _generate_serp_queries(
    *,
    call_llm_text: CallLLMText,
    extract_json_obj: ExtractJsonObj,
    strict_llm: bool,
    llm_model: str,
    subject: str,
    knowledge_point: str,
    seed_query: str,
    query_hint: str,
    preset: str,
    num_queries: int,
    learnings: List[str],
    prev_queries: List[str],
    llm_sem: asyncio.Semaphore,
) -> List[Dict[str, str]]:
    n = max(1, min(int(num_queries or 0), 12))
    prev_q = _dedup_strings([str(x or "") for x in (prev_queries or [])], keep=80)
    learn = _dedup_strings([_clip_text(str(x or ""), max_chars=200) for x in (learnings or [])], keep=20)

    # Fallback when LLM is not configured.
    if not llm_model:
        tpl = [
            f"{seed_query} 定义",
            f"{seed_query} 性质 定理",
            f"{seed_query} 充分必要条件",
            f"{seed_query} 证明 思路",
            f"{seed_query} 常见误区 反例",
            f"{seed_query} 例题 应用",
        ]
        out: List[Dict[str, str]] = []
        for q in tpl:
            q = re.sub(r"\s+", " ", str(q or "")).strip()
            if q:
                out.append({"query": q, "research_goal": ""})
            if len(out) >= n:
                break
        return out

    prompt = {
        "subject": subject,
        "knowledge_point": knowledge_point,
        "seed_query": seed_query,
        "query_hint": query_hint,
        "preset": preset,
        "previous_queries": prev_q[:25],
        "previous_learnings": learn[:12],
        "requirements": [
            f"Generate <= {n} non-duplicate web search queries. Do not repeat previous_queries.",
            "Match the user's/topic language when practical; short English keywords or symbols are allowed when helpful.",
            "覆盖角度：定义/直观理解/关键结论与条件/常见误区/证明骨架/应用与典型题。",
            "Each query must be <= 80 characters. Do not output anything outside JSON.",
            "Return JSON: queries:[{query,research_goal}]. research_goal is one sentence explaining the query goal.",
        ],
        "output_schema": {"queries": [{"query": "string", "research_goal": "string"}]},
    }

    async with llm_sem:
        text = await call_llm_text(
            messages=[
                {"role": "system", "content": _search_strategy_system_prompt()},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=llm_model,
            temperature=0.2,
            max_tokens=1600,
            response_format={"type": "json_object"},
            raise_on_fail=strict_llm,
        )

    obj = extract_json_obj(text)
    items = obj.get("queries") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        if strict_llm:
            raise RuntimeError(f"llm_generate_serp_queries_failed: invalid_json model={llm_model}")
        return []

    out: List[Dict[str, str]] = []
    seen: set[str] = set(x.lower() for x in prev_q)
    for it in items:
        if not isinstance(it, dict):
            continue
        q = re.sub(r"\s+", " ", str(it.get("query") or "")).strip()
        goal = str(it.get("research_goal") or it.get("researchGoal") or "").strip()
        if not q:
            continue
        if len(q) > 90:
            q = q[:90].rstrip() + "…"
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"query": q, "research_goal": goal})
        if len(out) >= n:
            break
    return out


async def _extract_learnings(
    *,
    call_llm_text: CallLLMText,
    extract_json_obj: ExtractJsonObj,
    strict_llm: bool,
    llm_model: str,
    preset: str,
    query: str,
    cleaned_results: List[Dict[str, Any]],
    num_learnings: int,
    num_followups: int,
    llm_sem: asyncio.Semaphore,
) -> Tuple[List[str], List[str]]:
    n_learn = max(1, min(int(num_learnings or 0), 8))
    n_fup = max(0, min(int(num_followups or 0), 8))

    # If LLM isn't configured, return a lightweight heuristic fallback.
    if not llm_model:
        learnings: List[str] = []
        for r in cleaned_results[: max(1, min(5, n_learn))]:
            title = str(r.get("title") or "").strip()
            snippet = str(r.get("snippet") or r.get("text") or "").strip()
            line = (title + "：" + snippet).strip("：").strip()
            if line:
                learnings.append(_clip_text(line, max_chars=220))
        followups: List[str] = []
        if n_fup > 0:
            followups = [
                f"{query} 的精确定义与符号约定是什么？",
                f"{query} 的关键性质/定理及适用条件是什么？",
                f"{query} 的常见误区/反例有哪些？",
            ][:n_fup]
        return (_dedup_strings(learnings, keep=20)[:n_learn], _dedup_strings(followups, keep=20)[:n_fup])

    docs: List[str] = []
    for r in cleaned_results[:6]:
        title = str(r.get("title") or "").strip()
        url_value = str(r.get("url") or "").strip()
        snippet = str(r.get("snippet") or "").strip()
        text_value = str(r.get("text") or "").strip()
        body = snippet or text_value
        body = _clip_text(body, max_chars=1600)
        if not (title or body):
            continue
        docs.append(
            "<doc>\n"
            + (f"title: {title}\n" if title else "")
            + (f"url: {url_value}\n" if url_value else "")
            + (f"content: {body}\n" if body else "")
            + "</doc>"
        )
        if len(docs) >= 4:
            break

    payload = {
        "query": query,
        "preset": preset,
        "requirements": [
            f"从下面的网页片段提炼 <= {n_learn} 条学习要点（信息密集，尽量包含条件/数字/日期）。",
            f"同时给出 <= {n_fup} 个 follow_up_questions 作为下一步深挖方向。"
            if n_fup > 0
            else "follow_up_questions 返回空数组。",
            "Do not fabricate. Omit uncertain information.",
            "Output only JSON: {learnings:string[], follow_up_questions:string[]}.",
        ],
        "docs": docs,
    }

    async with llm_sem:
        text = await call_llm_text(
            messages=[
                {"role": "system", "content": _learning_extraction_system_prompt()},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            model=llm_model,
            temperature=0.2,
            max_tokens=1600,
            response_format={"type": "json_object"},
            raise_on_fail=strict_llm,
        )

    obj = extract_json_obj(text)
    learnings_raw = obj.get("learnings") if isinstance(obj, dict) else None
    followups_raw = obj.get("follow_up_questions") if isinstance(obj, dict) else None
    if strict_llm and not isinstance(learnings_raw, list):
        raise RuntimeError(f"llm_extract_learnings_failed: invalid_json model={llm_model}")

    learnings = _dedup_strings(
        [str(x or "") for x in (learnings_raw or [])] if isinstance(learnings_raw, list) else [],
        keep=40,
    )
    followups = _dedup_strings(
        [str(x or "") for x in (followups_raw or [])] if isinstance(followups_raw, list) else [],
        keep=20,
    )
    return (learnings[:n_learn], followups[:n_fup] if n_fup > 0 else [])


async def deep_research(
    *,
    call_llm_text: CallLLMText,
    extract_json_obj: ExtractJsonObj,
    strict_llm: bool,
    llm_model: str,
    knowledge_point: str,
    subject: str,
    seed_query: str,
    search_func: SearchFunc,
    search_provider_name: str = "deepresearch",
    query_hint: str = "",
    preset: str = "",
    include_summary: bool = True,
    text_max_length: int = 2600,
    keep_sources: int = 12,
    # Optional overrides (caller should clamp, but we also clamp defensively)
    breadth: Optional[int] = None,
    depth: Optional[int] = None,
    max_queries: Optional[int] = None,
    per_query_results: Optional[int] = None,
    concurrency: Optional[int] = None,
    learnings_per_query: Optional[int] = None,
    prev_queries: Optional[List[str]] = None,
    prev_summary: str = "",
) -> Dict[str, Any]:
    """Deep multi-round web search using a pluggable search function + LLM (inspired by open-deep-research).

    Returns a dict with: results, queries, summary (optional), learnings, directions, errors.
    """

    if not search_func:
        return {"success": False, "provider": search_provider_name, "error": "No search function provided", "results": []}

    seed_query = re.sub(r"\s+", " ", str(seed_query or "")).strip()
    if not seed_query:
        return {"success": False, "provider": search_provider_name, "error": "empty query", "results": []}

    preset = str(preset or "").strip().lower()
    default_breadth, default_depth, default_max_q = deepresearch_defaults(preset)

    breadth_n = _clamp_int(breadth, default=default_breadth, min_value=1, max_value=12)
    depth_n = _clamp_int(depth, default=default_depth, min_value=1, max_value=6)
    max_q = _clamp_int(max_queries, default=default_max_q, min_value=3, max_value=60)
    per_q = _clamp_int(per_query_results, default=5, min_value=1, max_value=10)
    conc = _clamp_int(concurrency, default=2, min_value=1, max_value=4)
    learn_per_q = _clamp_int(learnings_per_query, default=3, min_value=1, max_value=6)
    keep_sources = _clamp_int(keep_sources, default=12, min_value=3, max_value=40)
    text_max_length = _clamp_int(text_max_length, default=2600, min_value=200, max_value=8000)

    prev_queries = prev_queries if isinstance(prev_queries, list) else []
    seen_keys: set[str] = set(_norm_query(str(x or "")) for x in prev_queries if str(x or "").strip())
    reserved: List[str] = []
    lock = asyncio.Lock()

    async def remaining_budget() -> int:
        async with lock:
            return max(0, int(max_q) - len(reserved))

    async def reserve(q: str) -> bool:
        qq = re.sub(r"\s+", " ", str(q or "")).strip()
        if not qq:
            return False
        key = _norm_query(qq)
        async with lock:
            if key in seen_keys:
                return False
            if len(reserved) >= int(max_q):
                return False
            seen_keys.add(key)
            reserved.append(qq)
            return True

    prev_summary = str(prev_summary or "").strip()
    learnings_ctx: List[str] = []
    if prev_summary:
        learnings_ctx.append(_clip_text(prev_summary, max_chars=1200))

    # Shared semaphores to avoid bursty fan-out.
    search_sem = asyncio.Semaphore(conc)
    llm_sem = asyncio.Semaphore(conc)

    async def run_search(q: str) -> Dict[str, Any]:
        async with search_sem:
            return await search_func(q, per_q)

    async def recurse(seed: str, *, breadth_now: int, depth_now: int, learnings_now: List[str]) -> Dict[str, Any]:
        if depth_now <= 0:
            return {"learnings": [], "queries": [], "results": [], "summary_parts": [], "errors": [], "directions": [], "provider_errors": []}

        remaining = await remaining_budget()
        if remaining <= 0:
            return {"learnings": [], "queries": [], "results": [], "summary_parts": [], "errors": [], "directions": [], "provider_errors": []}

        want = max(1, min(int(breadth_now or 0), remaining))
        serp = await _generate_serp_queries(
            call_llm_text=call_llm_text,
            extract_json_obj=extract_json_obj,
            strict_llm=strict_llm,
            llm_model=llm_model,
            subject=subject,
            knowledge_point=knowledge_point,
            seed_query=seed,
            query_hint=query_hint,
            preset=preset,
            num_queries=want,
            learnings=learnings_now,
            prev_queries=[*prev_queries, *reserved],
            llm_sem=llm_sem,
        )
        if not serp:
            return {"learnings": [], "queries": [], "results": [], "summary_parts": [], "errors": [], "directions": [], "provider_errors": []}

        async def one(serp_item: Dict[str, str]) -> Dict[str, Any]:
            q = str(serp_item.get("query") or "").strip()
            goal = str(serp_item.get("research_goal") or "").strip()
            if not q:
                return {
                    "learnings": [],
                    "queries": [],
                    "results": [],
                    "summary_parts": [],
                    "errors": [],
                    "directions": [],
                    "provider_errors": [],
                }
            ok = await reserve(q)
            if not ok:
                return {
                    "learnings": [],
                    "queries": [],
                    "results": [],
                    "summary_parts": [],
                    "errors": [],
                    "directions": [],
                    "provider_errors": [],
                }

            res = await run_search(q)
            raw_results = res.get("results") if isinstance(res, dict) else []
            raw_results = raw_results if isinstance(raw_results, list) else []

            cleaned: List[Dict[str, Any]] = []
            for r in raw_results:
                if not isinstance(r, dict):
                    continue
                rr = dict(r)
                rr.setdefault("source_query", q)
                cleaned.append(_postprocess_web_search_result(rr))

            errors: List[str] = []
            provider_errors: List[str] = []
            if isinstance(res, dict) and res.get("error") and not cleaned:
                raw_err = str(res.get("error") or "").strip()
                # "errors" keeps the query context for observability; "provider_errors"
                # stays raw so provider health matchers never see the query text.
                errors.append(f"{q}: {raw_err}")
                provider_errors.append(raw_err)

            learnings, directions = (
                await _extract_learnings(
                    call_llm_text=call_llm_text,
                    extract_json_obj=extract_json_obj,
                    strict_llm=strict_llm,
                    llm_model=llm_model,
                    preset=preset,
                    query=q,
                    cleaned_results=cleaned,
                    num_learnings=learn_per_q,
                    num_followups=max(0, min(6, (breadth_now + 1) // 2)),
                    llm_sem=llm_sem,
                )
                if (include_summary or depth_now > 1)
                else ([], [])
            )

            summary_parts: List[str] = []
            if include_summary and learnings:
                block = "\n".join([f"- {x}" for x in learnings[:learn_per_q] if str(x or "").strip()])
                if block:
                    summary_parts.append(f"【{q}】\n{block}")

            if depth_now > 1 and directions:
                new_breadth = max(1, (breadth_now + 1) // 2)
                next_seed = "\n".join(
                    [
                        f"Previous research goal: {goal}" if goal else "Previous research goal: (unknown)",
                        "Follow-up research directions:",
                        *[f"- {x}" for x in directions[: max(1, min(6, new_breadth))]],
                    ]
                ).strip()
                deeper = await recurse(
                    next_seed,
                    breadth_now=new_breadth,
                    depth_now=depth_now - 1,
                    learnings_now=[*learnings_now, *learnings],
                )
            else:
                deeper = {
                    "learnings": [],
                    "queries": [],
                    "results": [],
                    "summary_parts": [],
                    "errors": [],
                    "directions": [],
                    "provider_errors": [],
                }

            return {
                "learnings": [*learnings, *list(deeper.get("learnings") or [])],
                "queries": [q, *list(deeper.get("queries") or [])],
                "results": [*cleaned, *list(deeper.get("results") or [])],
                "summary_parts": [*summary_parts, *list(deeper.get("summary_parts") or [])],
                "errors": [*errors, *list(deeper.get("errors") or [])],
                "directions": [*directions, *list(deeper.get("directions") or [])],
                "provider_errors": [*provider_errors, *list(deeper.get("provider_errors") or [])],
            }

        branches = await asyncio.gather(*[one(it) for it in serp])
        merged: Dict[str, Any] = {
            "learnings": [],
            "queries": [],
            "results": [],
            "summary_parts": [],
            "errors": [],
            "directions": [],
            "provider_errors": [],
        }
        for b in branches:
            if not isinstance(b, dict):
                continue
            for k in ("learnings", "queries", "results", "summary_parts", "errors", "directions", "provider_errors"):
                if isinstance(b.get(k), list):
                    merged[k].extend(b.get(k) or [])
        return merged

    deep = await recurse(seed_query, breadth_now=breadth_n, depth_now=depth_n, learnings_now=learnings_ctx)

    all_learnings = _dedup_strings([str(x or "") for x in (deep.get("learnings") or [])], keep=60)
    all_queries = _dedup_strings([str(x or "") for x in ([*reserved, *list(deep.get("queries") or [])])], keep=60)
    all_results = _dedup_results([x for x in (deep.get("results") or []) if isinstance(x, dict)], keep=keep_sources)
    errors = _dedup_strings([str(x or "") for x in (deep.get("errors") or [])], keep=12)
    provider_errors = _dedup_strings([str(x or "") for x in (deep.get("provider_errors") or [])], keep=12)
    directions = _dedup_strings([str(x or "") for x in (deep.get("directions") or [])], keep=12)

    summary_parts = _dedup_strings([str(x or "") for x in (deep.get("summary_parts") or [])], keep=30)
    summary_value = "\n\n".join(summary_parts).strip() if include_summary else ""
    if include_summary and not summary_value and all_learnings:
        summary_value = "\n".join([f"- {x}" for x in all_learnings[:10]])
    if include_summary and summary_value and len(summary_value) > 8000:
        summary_value = summary_value[:7999].rstrip() + "…"

    return {
        "success": True,
        "provider": search_provider_name,
        "knowledge_point": knowledge_point,
        "query": seed_query,
        "queries": all_queries[:40],
        "results": all_results,
        "include_summary": bool(include_summary),
        "summary": summary_value,
        "learnings": all_learnings[:40],
        "directions": directions[:12],
        "errors": errors[:6],
        "provider_errors": provider_errors[:6],
        "depth": depth_n,
        "breadth": breadth_n,
        "max_queries": max_q,
    }


async def deep_research_exa(**kwargs: Any) -> Dict[str, Any]:
    """Backward-compatible wrapper using Exa as the search function."""
    from backend.integrations.mcp.search.exa import EXA_API_KEY, exa_search

    text_max_length = int(kwargs.get("text_max_length") or 2600)

    async def _exa_search_func(query: str, num_results: int) -> Dict[str, Any]:
        return await exa_search(
            query=query,
            num_results=min(num_results, 10),
            use_autoprompt=True,
            type="neural",
            include_text=True,
            text_max_length=min(text_max_length, 2600),
        )

    if "search_func" not in kwargs:
        kwargs["search_func"] = _exa_search_func if EXA_API_KEY else None
    if "search_provider_name" not in kwargs:
        kwargs["search_provider_name"] = "exa-deepresearch"
    return await deep_research(**kwargs)
