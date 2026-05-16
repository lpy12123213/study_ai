from __future__ import annotations

from typing import Any

from backend.mcp.search._base import FunctionSearchProvider, SearchProvider, register_search_provider


async def _bigmodel_search(query: str, limit: int) -> dict[str, Any]:
    from backend.mcp.search.bigmodel import web_search_with_bigmodel_mcp

    return await web_search_with_bigmodel_mcp(query=query, limit=limit)


async def _exa_search(query: str, limit: int) -> dict[str, Any]:
    from backend.mcp.search.exa import exa_search

    return await exa_search(query, num_results=limit)


async def _github_search(query: str, limit: int) -> dict[str, Any]:
    from backend.mcp.search.github import github_search_repositories

    return await github_search_repositories(query, limit=limit)


async def _mediawiki_search(query: str, limit: int) -> dict[str, Any]:
    from backend.mcp.search.mediawiki import mediawiki_search

    return await mediawiki_search(query, base_url="https://zh.wikipedia.org/", search_results=limit)


async def _metaso_search(query: str, limit: int) -> dict[str, Any]:
    from backend.mcp.search.metaso import metaso_search

    return await metaso_search(query=query, size=limit)


async def _stackexchange_search(query: str, limit: int) -> dict[str, Any]:
    from backend.mcp.search.stackexchange import stackexchange_search

    return await stackexchange_search(query, site="math.stackexchange", limit=limit)


async def _tavily_search(query: str, limit: int) -> dict[str, Any]:
    from backend.mcp.search.tavily import tavily_search

    return await tavily_search(query, max_results=limit)


async def _wikipedia_search(query: str, limit: int) -> dict[str, Any]:
    from backend.mcp.search.wikipedia import wikipedia_search

    return await wikipedia_search(query, search_results=limit)


async def _zhihu_fetch(query: str, limit: int) -> dict[str, Any]:
    from urllib.parse import urlparse

    from backend.mcp.search.zhihu import ZhihuFetcher

    parsed = urlparse(str(query or "").strip())
    if parsed.netloc.lower() not in {"www.zhihu.com", "zhuanlan.zhihu.com", "zhihu.com"}:
        return {
            "success": False,
            "provider": "zhihu",
            "query": query,
            "error": "zhihu provider expects a Zhihu URL",
            "results": [],
        }
    result = await ZhihuFetcher().fetch(query)
    data = result.to_dict()
    if not data.get("success"):
        return {"success": False, "provider": "zhihu", "query": query, "error": data.get("error"), "results": []}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    if not items:
        items = [
            {
                "title": data.get("title") or "",
                "url": data.get("url") or query,
                "text": data.get("content_markdown") or "",
            }
        ]
    return {"success": True, "provider": "zhihu", "query": query, "results": items[: max(1, int(limit or 1))]}


PROVIDERS: dict[str, SearchProvider] = {
    "bigmodel": FunctionSearchProvider("bigmodel", _bigmodel_search),
    "exa": FunctionSearchProvider("exa", _exa_search),
    "github": FunctionSearchProvider("github", _github_search),
    "mediawiki": FunctionSearchProvider("mediawiki", _mediawiki_search),
    "metaso": FunctionSearchProvider("metaso", _metaso_search),
    "stackexchange": FunctionSearchProvider("stackexchange", _stackexchange_search),
    "tavily": FunctionSearchProvider("tavily", _tavily_search),
    "wikipedia": FunctionSearchProvider("wikipedia", _wikipedia_search),
    "zhihu": FunctionSearchProvider("zhihu", _zhihu_fetch),
}


def install_default_search_providers() -> dict[str, SearchProvider]:
    for name, provider in PROVIDERS.items():
        register_search_provider(name, provider)
    return dict(PROVIDERS)


install_default_search_providers()
