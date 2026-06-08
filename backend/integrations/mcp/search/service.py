"""Shared web-search orchestration for MCP and chat tools."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)

WEB_SEARCH_PROVIDERS = {"auto", "tavily", "exa", "bigmodel"}
WEB_SEARCH_MODES = {"trending", "patterns"}


def _clean_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        if value is None or isinstance(value, bool):
            return default
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _provider_has_key(provider: str) -> bool:
    provider_name = str(provider or "").strip().lower()
    try:
        if provider_name == "tavily":
            from backend.integrations.mcp.search import tavily

            return bool(str(getattr(tavily, "TAVILY_API_KEY", "") or "").strip())
        if provider_name == "exa":
            from backend.integrations.mcp.search import exa

            return bool(str(getattr(exa, "EXA_API_KEY", "") or "").strip())
        if provider_name == "bigmodel":
            from backend.integrations.mcp.search import bigmodel

            return bool(str(getattr(bigmodel, "ZHIPU_API_KEY", "") or "").strip())
    except ImportError:
        return False
    return False


def _choose_provider(provider: str) -> str:
    provider_name = str(provider or "auto").strip().lower() or "auto"
    if provider_name not in WEB_SEARCH_PROVIDERS:
        provider_name = "auto"
    if provider_name != "auto":
        return provider_name

    for candidate in ("tavily", "exa", "bigmodel"):
        if _provider_has_key(candidate):
            return candidate
    return ""


def _provider_config_error(query: str, provider: str) -> Dict[str, Any]:
    provider_label = provider if provider and provider != "auto" else "auto"
    return {
        "success": False,
        "provider": provider_label,
        "query": query,
        "error": "No web search provider API key configured. Set TAVILY_API_KEY, EXA_API_KEY, or ZHIPU_API_KEY.",
        "results": [],
    }


def _trim(text: Any, max_chars: int = 900) -> str:
    value = str(text or "").strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "..."


def _normalize_results(items: Any, *, limit: int) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []

    results: List[Dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        snippet = _trim(
            item.get("snippet")
            or item.get("summary")
            or item.get("text")
            or item.get("content")
            or item.get("description")
            or ""
        )
        published = str(item.get("published_date") or item.get("publishedDate") or "").strip()
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "published_date": published,
            }
        )
    return results


async def _run_tavily_search(*, query: str, limit: int, mode: str, recency_days: int) -> Dict[str, Any]:
    from backend.integrations.mcp.search import tavily

    res = await tavily.tavily_search(
        query=query,
        max_results=limit,
        search_depth="basic",
        include_answer=False,
        include_raw_content=False,
        topic="news" if mode == "trending" else "general",
        days=recency_days if mode == "trending" else None,
    )
    if not isinstance(res, dict) or not res.get("success"):
        return {
            "success": False,
            "provider": str((res or {}).get("provider") or "tavily"),
            "query": query,
            "error": str((res or {}).get("error") or "tavily_search_failed"),
            "results": [],
        }
    return {
        "success": True,
        "provider": "tavily",
        "query": query,
        "results": _normalize_results(res.get("results"), limit=limit),
        **({"answer": str(res.get("answer") or "").strip()} if str(res.get("answer") or "").strip() else {}),
    }


async def _run_exa_search(*, query: str, limit: int, mode: str, recency_days: int) -> Dict[str, Any]:
    from backend.integrations.mcp.search import exa

    category: Optional[str] = None
    start_published_date: Optional[str] = None
    end_published_date: Optional[str] = None
    if mode == "trending":
        category = "news"
        today = datetime.now().date()
        end_published_date = today.isoformat()
        start_published_date = (today - timedelta(days=recency_days)).isoformat()

    res = await exa.exa_search(
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
    return {
        "success": True,
        "provider": "exa",
        "query": query,
        "results": _normalize_results(res.get("results"), limit=limit),
    }


async def _run_bigmodel_search(*, query: str, limit: int, model: str) -> Dict[str, Any]:
    from backend.integrations.mcp.search.bigmodel import web_search_with_bigmodel_mcp

    res = await web_search_with_bigmodel_mcp(query=query, limit=limit, model=model)
    if not isinstance(res, dict):
        return {
            "success": False,
            "provider": "bigmodel",
            "query": query,
            "error": "bigmodel_search_failed",
            "results": [],
        }
    return {
        **res,
        "success": bool(res.get("success")),
        "provider": str(res.get("provider") or "bigmodel"),
        "query": query,
        "results": _normalize_results(res.get("results"), limit=limit),
    }


async def run_web_search(
    query: str,
    *,
    limit: int = 5,
    provider: str = "auto",
    mode: str = "trending",
    recency_days: int = 180,
    model: str = "",
) -> Dict[str, Any]:
    """Run configured web search and return a common result shape."""

    query_clean = str(query or "").strip()
    provider_in = str(provider or "auto").strip().lower() or "auto"
    if provider_in not in WEB_SEARCH_PROVIDERS:
        provider_in = "auto"
    mode_in = str(mode or "trending").strip().lower() or "trending"
    if mode_in not in WEB_SEARCH_MODES:
        mode_in = "trending"
    limit_in = _clean_int(limit, 5, minimum=1, maximum=10)
    recency_in = _clean_int(recency_days, 180, minimum=1, maximum=3650)

    if not query_clean:
        return {"success": False, "provider": provider_in, "query": "", "error": "query is required", "results": []}

    selected = _choose_provider(provider_in)
    if not selected or not _provider_has_key(selected):
        return _provider_config_error(query_clean, provider_in)

    try:
        if selected == "tavily":
            result = await _run_tavily_search(query=query_clean, limit=limit_in, mode=mode_in, recency_days=recency_in)
        elif selected == "exa":
            result = await _run_exa_search(query=query_clean, limit=limit_in, mode=mode_in, recency_days=recency_in)
        else:
            result = await _run_bigmodel_search(query=query_clean, limit=limit_in, model=str(model or "").strip())
    except Exception as exc:  # noqa: BLE001 - provider failures must degrade to a tool error
        logger.warning("shared_web_search_failed", extra={"provider": selected}, exc_info=True)
        result = {
            "success": False,
            "provider": selected,
            "query": query_clean,
            "error": f"{selected}_search_failed: {exc}",
            "results": [],
        }

    if isinstance(result, dict):
        result["mode"] = mode_in
        result["recency_days"] = recency_in
        result["limit"] = limit_in
    return result
