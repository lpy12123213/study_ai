"""Generic MediaWiki search + extract utility.

This is a lightweight wrapper around the official MediaWiki API (w/api.php).
It can be used with Wikipedia as well as other MediaWiki-powered sites.

Typical base_url examples:
- https://zh.wikipedia.org/
- https://en.wikipedia.org/
- https://proofwiki.org/wiki/
- https://zh.wikibooks.org/
"""

from __future__ import annotations

import asyncio
import random
import re
from typing import Any, Dict, List, Optional

import httpx

from backend.core.settings import API_TIMEOUT


def _clip(text: str, *, max_len: int) -> str:
    if max_len <= 0:
        return ""
    t = text or ""
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _normalize_text(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t\f\v]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _sentence_summary(text: str, *, sentences: int) -> str:
    if sentences <= 0:
        return ""
    t = _normalize_text(text)
    if not t:
        return ""
    parts = re.split(r"(?<=[。！？!?\.])\s+", t)
    picked: List[str] = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        picked.append(s)
        if len(picked) >= sentences:
            break
    if picked:
        return " ".join(picked).strip()
    return _clip(t, max_len=320)


def _normalize_base_url(base_url: str) -> str:
    raw = (base_url or "").strip()
    if not raw:
        return ""
    # Ensure it ends with a slash so httpx base_url resolves "w/api.php" correctly.
    return raw.rstrip("/") + "/"


async def _mw_search_titles(
    *,
    query: str,
    search_results: int,
    client: httpx.AsyncClient,
) -> List[str]:
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": max(1, min(int(search_results or 5), 10)),
        "format": "json",
        "utf8": "1",
    }
    retry_statuses = {408, 429, 500, 502, 503, 504}
    last_exc: Optional[Exception] = None
    data: Any = {}

    for attempt in range(3):
        try:
            resp = await client.get("w/api.php", params=params)
            if resp.status_code in retry_statuses and attempt < 2:
                await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                continue
            raise last_exc

    hits: List[str] = []
    query_obj = data.get("query") if isinstance(data, dict) else {}
    search_items = query_obj.get("search") if isinstance(query_obj, dict) else []
    if isinstance(search_items, list):
        for it in search_items[:10]:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "").strip()
            if title:
                hits.append(title)

    # De-dup while preserving order.
    out: List[str] = []
    seen: set[str] = set()
    for t in hits:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


async def _mw_fetch_extract(
    *,
    title: str,
    max_content_length: int,
    client: httpx.AsyncClient,
) -> Dict[str, Any]:
    params = {
        "action": "query",
        "prop": "extracts|info|pageprops",
        "titles": title,
        "explaintext": "1",
        "exsectionformat": "plain",
        "exchars": max(200, min(int(max_content_length or 4000), 8000)),
        "inprop": "url",
        "ppprop": "disambiguation",
        "redirects": "1",
        "format": "json",
        "utf8": "1",
    }
    retry_statuses = {408, 429, 500, 502, 503, 504}
    last_exc: Optional[Exception] = None
    data: Any = {}

    for attempt in range(3):
        try:
            resp = await client.get("w/api.php", params=params)
            if resp.status_code in retry_statuses and attempt < 2:
                await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                continue
            raise last_exc
    pages = (data.get("query", {}) or {}).get("pages", {}) or {}

    page_obj: Optional[Dict[str, Any]] = None
    for _, v in pages.items():
        if isinstance(v, dict):
            page_obj = v
            break
    if not page_obj:
        return {"success": False, "error": "empty mediawiki response"}

    if page_obj.get("missing") is not None:
        return {"success": False, "error": "page missing"}

    extract = _normalize_text(str(page_obj.get("extract") or ""))
    url = str(page_obj.get("fullurl") or "").strip()
    resolved_title = str(page_obj.get("title") or title).strip()

    pageprops = page_obj.get("pageprops")
    is_disambiguation = isinstance(pageprops, dict) and "disambiguation" in pageprops

    return {
        "success": True,
        "title": resolved_title,
        "url": url,
        "content": _clip(extract, max_len=int(max_content_length or 0)),
        "is_disambiguation": is_disambiguation,
    }


async def mediawiki_search(
    query: str,
    *,
    base_url: str,
    sentences: int = 4,
    search_results: int = 5,
    max_content_length: int = 4000,
) -> Dict[str, Any]:
    """Search and fetch content from a MediaWiki site."""

    q = (query or "").strip()
    if not q:
        return {"success": False, "error": "query 不能为空", "provider": "mediawiki_api"}

    base = _normalize_base_url(base_url)
    if not base:
        return {"success": False, "error": "base_url 不能为空", "provider": "mediawiki_api"}

    timeout = float(API_TIMEOUT or 120)
    try:
        async with httpx.AsyncClient(
            base_url=base,
            timeout=min(max(timeout, 10.0), 120.0),
            headers={"User-Agent": "study_ai/1.0 (mediawiki_search)"},
            follow_redirects=True,
        ) as client:
            hits = await _mw_search_titles(query=q, search_results=search_results, client=client)
            title = (hits[0] if hits else q).strip()
            disambiguation_options = hits[1:10] if len(hits) > 1 else []

            fetched = await _mw_fetch_extract(
                title=title,
                max_content_length=max_content_length,
                client=client,
            )

            # If this is a disambiguation page, try a few alternative hits.
            if fetched.get("success") and fetched.get("is_disambiguation"):
                for opt in disambiguation_options[:3]:
                    alt = await _mw_fetch_extract(
                        title=opt,
                        max_content_length=max_content_length,
                        client=client,
                    )
                    if alt.get("success") and not alt.get("is_disambiguation"):
                        fetched = alt
                        break

            if not fetched.get("success"):
                return {
                    "success": False,
                    "query": q,
                    "base_url": base,
                    "error": str(fetched.get("error") or "unknown error"),
                    "search_hits": hits,
                    "disambiguation_options": disambiguation_options,
                    "provider": "mediawiki_api",
                }

            content = str(fetched.get("content") or "")
            return {
                "success": True,
                "query": q,
                "base_url": base,
                "title": str(fetched.get("title") or title),
                "url": str(fetched.get("url") or ""),
                "summary": _sentence_summary(content, sentences=sentences),
                "content": content,
                "search_hits": hits,
                "disambiguation_options": disambiguation_options,
                "provider": "mediawiki_api",
            }
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        return {"success": False, "query": q, "base_url": base, "error": str(exc), "provider": "mediawiki_api"}
