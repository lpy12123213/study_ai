"""MCP tool specs, executors and the LLM-driven material search loop.

The OpenAI-style tool *schemas* live in :mod:`backend.cli.tool_specs` and the
deterministic Markdown fallback in :mod:`backend.cli.fallback_markdown`; this
module keeps the thin CLI wrappers plus the executors that actually call the
search/compute integrations and the agent loop that stitches them together.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from backend.llm.client import chat_completion

from .helpers import _resolve_cli_mcp_search_model, logger
from .render import _format_tool_call_log, _format_tool_result_log
from .tool_aliases import (
    _exec_python_scientific_compute_tool,
    _fallback_material_markdown,
    _mcp_web_search_tool_spec,
    _python_scientific_compute_tool_spec,
)
from .tool_aliases import (
    _fallback_search_markdown as _fallback_search_markdown,
)


async def _exec_mcp_web_search_tool(
    *,
    query: str,
    limit: int,
    provider: str,
    mode: str,
    recency_days: int,
) -> Dict[str, Any]:
    """Execute our MCP web search tool (Tavily preferred, Exa/BigModel fallback)."""

    query = str(query or "").strip()
    if not query:
        return {"success": False, "provider": "mcp_web_search", "error": "query 不能为空", "results": []}

    limit = max(1, min(int(limit or 5), 10))
    provider_in = str(provider or "auto").strip().lower() or "auto"
    if provider_in not in {"auto", "tavily", "exa", "bigmodel"}:
        provider_in = "auto"

    mode_in = str(mode or "trending").strip()
    if mode_in not in {"trending", "patterns"}:
        mode_in = "trending"
    days = max(1, min(int(recency_days or 180), 3650))

    if provider_in == "auto":
        try:
            from backend.integrations.mcp.search.tavily import TAVILY_API_KEY as _TAVILY_API_KEY

            has_tavily = bool(str(_TAVILY_API_KEY or "").strip())
        except ImportError:
            has_tavily = False
        try:
            from backend.integrations.mcp.search.exa import EXA_API_KEY as _EXA_API_KEY

            has_exa = bool(str(_EXA_API_KEY or "").strip())
        except ImportError:
            has_exa = False
        provider_in = "tavily" if has_tavily else "exa" if has_exa else "bigmodel"

    if provider_in == "tavily":
        try:
            from backend.integrations.mcp.search.tavily import tavily_search
        except ImportError as exc:
            return {
                "success": False,
                "provider": "tavily",
                "query": query,
                "error": f"import_tavily_failed: {exc}",
                "results": [],
            }

        res = await tavily_search(
            query=query,
            max_results=limit,
            search_depth="basic",
            include_answer=False,
            include_raw_content=False,
            topic="news" if mode_in == "trending" else "general",
            days=days if mode_in == "trending" else None,
        )
        if not isinstance(res, dict) or not res.get("success"):
            return {
                "success": False,
                "provider": str((res or {}).get("provider") or "tavily"),
                "query": query,
                "error": str((res or {}).get("error") or "tavily_search_failed"),
                "results": [],
            }

        results_in = res.get("results") if isinstance(res.get("results"), list) else []
        results_out: List[Dict[str, Any]] = []
        for item in results_in[:limit]:
            if not isinstance(item, dict):
                continue
            snippet = str(item.get("snippet") or item.get("text") or "").strip()
            if len(snippet) > 800:
                snippet = snippet[:800].rstrip() + "…"
            results_out.append(
                {
                    "title": str(item.get("title") or "").strip(),
                    "url": str(item.get("url") or "").strip(),
                    "snippet": snippet,
                    "published_date": str(item.get("published_date") or "").strip(),
                }
            )

        return {
            "success": True,
            "provider": str(res.get("provider") or "tavily"),
            "query": query,
            "mode": mode_in,
            "recency_days": days,
            "results": results_out,
        }

    if provider_in == "exa":
        try:
            from backend.integrations.mcp.search.exa import exa_search
        except ImportError as exc:
            return {"success": False, "provider": "exa", "query": query, "error": f"import_exa_failed: {exc}", "results": []}

        category: Optional[str] = None
        start_published_date: Optional[str] = None
        end_published_date: Optional[str] = None
        if mode_in == "trending":
            category = "news"
            today = datetime.now().date()
            end_published_date = today.isoformat()
            start_published_date = (today - timedelta(days=days)).isoformat()

        res = await exa_search(
            query=query,
            num_results=limit,
            category=category,
            start_published_date=start_published_date,
            end_published_date=end_published_date,
            include_text=False,
            include_summary=True,
            include_highlights=True,
        )
        if not isinstance(res, dict) or not res.get("success"):
            return {
                "success": False,
                "provider": str((res or {}).get("provider") or "exa"),
                "query": query,
                "error": str((res or {}).get("error") or "exa_search_failed"),
                "results": [],
            }

        results_in = res.get("results") if isinstance(res.get("results"), list) else []
        results_out: List[Dict[str, Any]] = []
        for item in results_in[:limit]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            published = str(item.get("published_date") or "").strip()
            snippet = str(item.get("summary") or "").strip()
            if not snippet:
                highlights = item.get("highlights") if isinstance(item.get("highlights"), list) else []
                snippet = str(highlights[0] if highlights else "").strip()
            if len(snippet) > 800:
                snippet = snippet[:800].rstrip() + "…"
            results_out.append({"title": title, "url": url, "snippet": snippet, "published_date": published})

        return {
            "success": True,
            "provider": str(res.get("provider") or "exa"),
            "query": query,
            "mode": mode_in,
            "recency_days": days,
            "results": results_out,
        }

    try:
        from backend.integrations.mcp.search.bigmodel import web_search_with_bigmodel_mcp
    except ImportError as exc:
        return {
            "success": False,
            "provider": "bigmodel",
            "query": query,
            "error": f"import_bigmodel_failed: {exc}",
            "results": [],
        }

    res = await web_search_with_bigmodel_mcp(query=query, limit=limit, model="")
    if not isinstance(res, dict) or not res.get("success"):
        return {
            "success": False,
            "provider": str((res or {}).get("provider") or "bigmodel"),
            "query": query,
            "error": str((res or {}).get("error") or "bigmodel_search_failed"),
            "detail": str((res or {}).get("detail") or "")[:2000],
            "results": [],
        }

    results_in = res.get("results") if isinstance(res.get("results"), list) else []
    results_out: List[Dict[str, Any]] = []
    for item in results_in[:limit]:
        if not isinstance(item, dict):
            continue
        results_out.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "snippet": str(item.get("snippet") or "").strip(),
            }
        )

    return {
        "success": True,
        "provider": str(res.get("provider") or "zhipu-bigmodel-mcp-web-search"),
        "model": str(res.get("model") or "").strip(),
        "query": query,
        "mode": mode_in,
        "recency_days": days,
        "results": results_out,
    }


async def _ai_search_materials_via_mcp(
    *,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    query: str,
    provider: str,
    mode: str,
    recency_days: int,
    limit: int,
    ui_log_tool: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Let the LLM call MCP-style tools to prepare study materials."""

    # This stage relies on tool-calling + citations. Prefer a tool-capable model by default,
    # and allow override via env var. Do NOT silently inherit a cheap/non-tool-capable
    # lesson_plan model here, otherwise we may get hallucinated "sources".
    effective_model = _resolve_cli_mcp_search_model()

    def _log(msg: str) -> None:
        if callable(ui_log_tool):
            try:
                ui_log_tool(msg)
            except Exception:  # noqa: BLE001 - UI log callback is external best-effort plumbing.
                logger.warning("question_generate_ui_log_failed", exc_info=True)
                return

    base_query = str(query or "").strip()
    if not base_query:
        tokens = [subject, topic]
        tokens = [str(x or "").strip() for x in tokens if str(x or "").strip()]
        if str(mode or "").strip() == "patterns":
            more = [difficulty, question_type, "真题", "解题思路", "出题规律"]
        else:
            year = datetime.now().year
            more = [str(year), "热点", "时兴", "素材", "案例", "真实数据"]
        more = [str(x or "").strip() for x in more if str(x or "").strip()]
        base_query = " ".join(tokens + more).strip()

    tools = [_mcp_web_search_tool_spec(), _python_scientific_compute_tool_spec()]
    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "你是一个出题素材检索助手。你必须先调用 mcp_web_search 搜索互联网资料，"
                "并可按需调用 python_scientific_compute 做公式验证、数值试算、样例构造或结果核对。"
                "随后输出一段 Markdown，包含：\n"
                "1) 5-10 条可用于出题的素材点/事实点（每条都要附带来源 url；不要编造）\n"
                "2) 如进行了计算，请给出可复用的计算结论或构造结果\n"
                "3) 每条素材点尽量与学科/知识点相关；如果不是直接相关，要说明如何转化为题目背景\n"
                "4) 语言简洁，不要输出与任务无关的解释。\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"学科: {subject}\n"
                f"主题: {topic}\n"
                f"难度: {difficulty}\n"
                f"题型: {question_type}\n"
                f"目标: {mode} (trending=时兴素材, patterns=真题规律)\n"
                f"recency_days: {int(recency_days or 180)}\n"
                f"limit: {int(limit or 5)}\n"
                f"provider: {provider}\n\n"
                f"请先搜索：{base_query}\n"
            ),
        },
    ]

    aggregated_tool_results: List[Dict[str, Any]] = []
    max_iters = 4
    for it in range(max_iters):
        res = await chat_completion(
            messages=messages,  # type: ignore[arg-type]
            model=effective_model,
            temperature=0.2,
            max_tokens=1600,
            tools=tools,
            tool_choice="auto",
            stream=False,
            raise_on_fail=False,
            retries=2,
            req_id_prefix="mcp-search",
        )

        tool_calls = list(res.tool_calls or [])
        if tool_calls:
            messages.append({"role": "assistant", "content": res.content or "", "tool_calls": tool_calls})
            for tc in tool_calls[:3]:
                fn = tc.get("function") if isinstance(tc, dict) else {}
                tool_name = str((fn or {}).get("name") or "").strip()
                tool_id = str(tc.get("id") or "").strip()
                raw_args = (fn or {}).get("arguments") if isinstance(fn, dict) else {}
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = raw_args if isinstance(raw_args, dict) else {}

                _log(_format_tool_call_log(tool_name or "unknown_tool", args))

                if tool_name == "mcp_web_search":
                    tool_query = str(args.get("query") or base_query).strip()
                    tool_limit = int(args.get("limit") or limit or 5)
                    tool_limit = max(1, min(tool_limit, 10))

                    # Respect CLI/user choice over the model's suggestion (prevents accidental provider flips).
                    forced_provider = str(provider or "").strip().lower()
                    if forced_provider in {"tavily", "exa", "bigmodel"}:
                        tool_provider = forced_provider
                    else:
                        tool_provider = str(args.get("provider") or "auto").strip()

                    forced_mode = str(mode or "").strip()
                    if forced_mode in {"trending", "patterns"}:
                        tool_mode = forced_mode
                    else:
                        tool_mode = str(args.get("mode") or "trending").strip()

                    tool_days = int(recency_days or 180)
                    tool_result = await _exec_mcp_web_search_tool(
                        query=tool_query,
                        limit=tool_limit,
                        provider=tool_provider,
                        mode=tool_mode,
                        recency_days=tool_days,
                    )
                elif tool_name == "python_scientific_compute":
                    tool_result = await _exec_python_scientific_compute_tool(
                        code=str(args.get("code") or "").strip(),
                        purpose=str(args.get("purpose") or "").strip(),
                        timeout_seconds=int(args.get("timeout_seconds") or 5),
                    )
                else:
                    tool_result = {"success": False, "error": f"unsupported_tool: {tool_name}", "provider": "cli"}

                if isinstance(tool_result, dict):
                    tool_result = {"tool_name": tool_name, **tool_result}
                _log(_format_tool_result_log(tool_name or "unknown_tool", tool_result if isinstance(tool_result, dict) else {"raw": tool_result}))

                if tool_id:
                    messages.append(
                        {"role": "tool", "tool_call_id": tool_id, "content": json.dumps(tool_result, ensure_ascii=False)}
                    )
                else:
                    messages.append({"role": "tool", "content": json.dumps(tool_result, ensure_ascii=False)})
                aggregated_tool_results.append(dict(tool_result) if isinstance(tool_result, dict) else {"raw": tool_result})
            continue

        # No tool calls: LLM finished.
        content = str(res.content or "").strip()
        if it == 0 and not aggregated_tool_results:
            # Enforce at least one real search call so the downstream material block can cite URLs.
            forced_args = {
                "query": base_query,
                "limit": int(limit or 5),
                "provider": str(provider or "auto").strip() or "auto",
                "mode": str(mode or "trending").strip() or "trending",
                "recency_days": int(recency_days or 180),
            }
            _log(_format_tool_call_log("mcp_web_search", forced_args))
            tool_result = await _exec_mcp_web_search_tool(
                query=base_query,
                limit=int(limit or 5),
                provider=str(provider or "auto").strip() or "auto",
                mode=str(mode or "trending").strip() or "trending",
                recency_days=int(recency_days or 180),
            )
            tool_payload = {"tool_name": "mcp_web_search", **(tool_result if isinstance(tool_result, dict) else {"raw": tool_result})}
            _log(_format_tool_result_log("mcp_web_search", tool_payload if isinstance(tool_payload, dict) else {"raw": tool_payload}))
            aggregated_tool_results.append(dict(tool_payload) if isinstance(tool_payload, dict) else {"raw": tool_payload})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "下面是 mcp_web_search 的搜索结果（JSON）。请基于这些结果输出所需 Markdown（每条素材点必须附带来源 url；不要编造）。\n\n"
                        f"```json\n{json.dumps(tool_payload, ensure_ascii=False)[:9000]}\n```"
                    ),
                }
            )
            continue
        if not content and aggregated_tool_results:
            content = _fallback_material_markdown(query=base_query, tool_results=aggregated_tool_results)
        return {
            "success": True,
            "query": base_query,
            "provider": provider,
            "mode": mode,
            "recency_days": int(recency_days or 180),
            "limit": int(limit or 5),
            "study_markdown": content,
            "tool_results": aggregated_tool_results[:10],
            "model": effective_model,
        }

    # Max iterations reached. Fallback to the last tool results.
    content = _fallback_material_markdown(query=base_query, tool_results=aggregated_tool_results) if aggregated_tool_results else ""
    return {
        "success": bool(content),
        "query": base_query,
        "provider": provider,
        "mode": mode,
        "recency_days": int(recency_days or 180),
        "limit": int(limit or 5),
        "study_markdown": content,
        "tool_results": aggregated_tool_results[:10],
        "model": effective_model,
        "error": "max_tool_iterations_reached",
    }
