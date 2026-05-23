from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict


class SearchHit(TypedDict, total=False):
    title: str
    url: str
    snippet: str
    content: str
    score: float
    provider: str
    raw: dict[str, Any]


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        ...


SearchFunction = Callable[[str, int], Awaitable[dict[str, Any]]]


DEFAULT_SEARCH_TIMEOUT_S = float(os.getenv("MCP_SEARCH_TIMEOUT_S") or "60")
DEFAULT_SEARCH_USER_AGENT = (
    os.getenv("MCP_SEARCH_USER_AGENT")
    or "StudyAI/1.0 (+https://github.com/local/study_ai; contact=local-admin)"
)


def build_search_headers(*, accept: str = "application/json", extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": DEFAULT_SEARCH_USER_AGENT,
    }
    if extra:
        headers.update({str(k): str(v) for k, v in extra.items() if k and v})
    return headers


def normalize_search_hits(provider: str, response: dict[str, Any], *, limit: int = 5) -> list[SearchHit]:
    """Normalize provider-specific result dictionaries into SearchHit rows."""

    raw_items: Any = response.get("results")
    if raw_items is None:
        raw_items = response.get("citations")
    if raw_items is None:
        raw_items = response.get("sources")
    if not isinstance(raw_items, list):
        raw_items = []

    hits: list[SearchHit] = []
    for item in raw_items[: max(1, min(int(limit or 5), 20))]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("full_name") or "").strip()
        url = str(item.get("url") or item.get("link") or item.get("html_url") or "").strip()
        snippet = str(
            item.get("snippet")
            or item.get("summary")
            or item.get("description")
            or item.get("text")
            or item.get("content")
            or ""
        ).strip()
        content = str(item.get("text") or item.get("content") or item.get("readme") or snippet).strip()
        hit: SearchHit = {
            "title": title,
            "url": url,
            "snippet": snippet[:800],
            "content": content[:4000],
            "provider": provider,
            "raw": item,
        }
        try:
            if item.get("score") is not None:
                hit["score"] = float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            pass
        hits.append(hit)
    return hits


@dataclass(frozen=True)
class FunctionSearchProvider:
    name: str
    search_func: SearchFunction
    default_kwargs: dict[str, Any] = field(default_factory=dict)

    async def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        q = str(query or "").strip()
        if not q:
            return []
        lim = max(1, min(int(limit or 5), 20))
        response = await self.search_func(q, lim)
        response = response if isinstance(response, dict) else {}
        return normalize_search_hits(self.name, response, limit=lim)


_PROVIDERS: dict[str, SearchProvider] = {}


def register_search_provider(name: str, provider: SearchProvider) -> SearchProvider:
    provider_name = str(name or "").strip().lower()
    if not provider_name:
        raise ValueError("provider name is required")
    _PROVIDERS[provider_name] = provider
    return provider


def get_search_provider(name: str) -> SearchProvider:
    provider_name = str(name or "").strip().lower()
    try:
        return _PROVIDERS[provider_name]
    except KeyError as exc:
        raise KeyError(f"unknown search provider: {provider_name}") from exc


def list_search_providers() -> dict[str, SearchProvider]:
    return dict(_PROVIDERS)
