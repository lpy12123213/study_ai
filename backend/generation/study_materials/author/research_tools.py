"""Thin search/browse tools for the author agent (design doc §8).

No LLM calls in this layer: query formulation is the author's own job.
Provider functions are injectable for tests."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

SerpFunc = Callable[[str, int], Awaitable[List[Dict[str, Any]]]]
FetchFunc = Callable[[str], Awaitable[str]]


class ResearchToolbox:
    def __init__(
        self,
        serp_func: Optional[SerpFunc] = None,
        fetch_func: Optional[FetchFunc] = None,
        wiki_func: Optional[SerpFunc] = None,
        *,
        timeout_s: float = 30.0,
    ) -> None:
        self._serp = serp_func or self._default_serp
        self._fetch = fetch_func or self._default_fetch
        self._wiki = wiki_func or self._default_wiki
        self._timeout = timeout_s

    async def search(self, query: str, n: int = 5) -> Dict[str, Any]:
        try:
            results = await asyncio.wait_for(self._serp(query, n), timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001 - re-raised with provider label for the agent
            raise RuntimeError(f"serp failed: {exc}") from exc
        return {"provider": "serp", "query": query, "results": results[:n]}

    async def search_wikipedia(self, query: str, n: int = 3) -> Dict[str, Any]:
        try:
            results = await asyncio.wait_for(self._wiki(query, n), timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001 - re-raised with provider label for the agent
            raise RuntimeError(f"wikipedia failed: {exc}") from exc
        return {"provider": "wikipedia", "query": query, "results": results[:n]}

    async def browse(self, url: str, *, max_chars: int = 4000) -> Dict[str, Any]:
        try:
            text = await asyncio.wait_for(self._fetch(url), timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"fetch failed: {exc}") from exc
        return {"url": url, "text": text[:max_chars]}

    @staticmethod
    async def _default_serp(query: str, n: int) -> List[Dict[str, Any]]:
        """Adapt the real Tavily entry: backend/integrations/mcp/search/tavily.tavily_search."""
        from backend.integrations.mcp.search.tavily import tavily_search

        data = await tavily_search(query, max_results=n)
        if not data.get("success"):
            raise RuntimeError(str(data.get("error") or "tavily search failed"))
        results = data.get("results")
        return list(results) if isinstance(results, list) else []

    @staticmethod
    async def _default_wiki(query: str, n: int) -> List[Dict[str, Any]]:
        """Adapt the real Wikipedia entry: backend/integrations/mcp/search/wikipedia.wikipedia_search."""
        from backend.integrations.mcp.search.wikipedia import wikipedia_search

        data = await wikipedia_search(query, search_results=max(1, min(int(n or 3), 10)))
        if not data.get("success"):
            raise RuntimeError(str(data.get("error") or "wikipedia search failed"))
        return [{
            "title": str(data.get("title") or query),
            "url": str(data.get("url") or ""),
            "content": str(data.get("summary") or data.get("content") or ""),
            "score": 0.8,
        }]

    @staticmethod
    async def _default_fetch(url: str) -> str:
        """Fetch a page and extract readable text.

        Mirrors the fetch/extract core of
        backend/agent/tools/search/browse_web_pages.BrowseWebPagesToolsMixin
        (httpx GET + BeautifulSoup visible-text extraction); that mixin is
        coupled to the legacy agent context and takes no plain URL, so it
        cannot be adapted directly here.
        """
        import httpx

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text or ""
        return await asyncio.to_thread(ResearchToolbox._extract_text, html)

    @staticmethod
    def _extract_text(html: str) -> str:
        from bs4 import BeautifulSoup

        from backend.agent.tools.utils.text_utils import _remove_ui_noise

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
            tag.decompose()
        body = soup.body or soup
        return _remove_ui_noise(body.get_text("\n", strip=True))
