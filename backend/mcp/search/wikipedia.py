"""Wikipedia lookup utility.

This module is used by the self-study agent to fetch encyclopedia-style
definitions and background info.

Notes:
- The `wikipedia` PyPI package is synchronous; we run it in a thread to avoid
  blocking the event loop.
- We return structured JSON so the agent can assemble Markdown later.
"""

from __future__ import annotations

import asyncio
import functools
import re
from typing import Any, Dict, List, Optional

import httpx

from backend.core.logging_utils import get_logger
from backend.core.settings import API_TIMEOUT

logger = get_logger(__name__)


async def _to_thread(func, /, *args, **kwargs):
    """Compat helper for Python 3.8+ (asyncio.to_thread is 3.9+)."""

    try:
        to_thread = asyncio.to_thread  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
    return await to_thread(func, *args, **kwargs)


def _clip(text: str, *, max_len: int) -> str:
    if max_len <= 0:
        return ""
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _normalize_text(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    # Collapse spaces while keeping paragraph breaks.
    t = re.sub(r"[ \t\f\v]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _sentence_summary(text: str, *, sentences: int) -> str:
    if sentences <= 0:
        return ""
    t = _normalize_text(text)
    if not t:
        return ""

    # Split by common sentence-ending punctuation (CN + EN) while keeping punctuation.
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
    # Fallback: clip to a reasonable length.
    return _clip(t, max_len=320)


async def _wikipedia_api_search(
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
    resp = await client.get("w/api.php", params=params)
    resp.raise_for_status()
    data = resp.json()

    hits: List[str] = []
    try:
        for it in (data.get("query", {}).get("search") or [])[:10]:
            title = str((it or {}).get("title") or "").strip()
            if title:
                hits.append(title)
    except (AttributeError, TypeError):
        hits = []

    # De-dup while preserving order
    out: List[str] = []
    seen: set[str] = set()
    for t in hits:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


async def _wikipedia_api_fetch(
    *,
    title: str,
    max_content_length: int,
    client: httpx.AsyncClient,
) -> Dict[str, Any]:
    # Fetch plain-text extract and full URL.
    params = {
        "action": "query",
        "prop": "extracts|info|pageprops",
        "titles": title,
        "explaintext": "1",
        "exsectionformat": "plain",
        # Let MediaWiki do the clipping, then we clip again defensively.
        "exchars": max(200, min(int(max_content_length or 4000), 8000)),
        "inprop": "url",
        "ppprop": "disambiguation",
        "redirects": "1",
        "format": "json",
        "utf8": "1",
    }
    resp = await client.get("w/api.php", params=params)
    resp.raise_for_status()
    data = resp.json()
    pages = (data.get("query", {}) or {}).get("pages", {}) or {}

    page_obj: Optional[Dict[str, Any]] = None
    for _, v in pages.items():
        if isinstance(v, dict):
            page_obj = v
            break
    if not page_obj:
        return {"success": False, "error": "empty wikipedia response"}

    if page_obj.get("missing") is not None:
        return {"success": False, "error": "page missing"}

    extract = _normalize_text(str(page_obj.get("extract") or ""))
    url = str(page_obj.get("fullurl") or "").strip()
    resolved_title = str(page_obj.get("title") or title).strip()

    is_disambiguation = False
    pageprops = page_obj.get("pageprops")
    if isinstance(pageprops, dict) and "disambiguation" in pageprops:
        is_disambiguation = True

    return {
        "success": True,
        "title": resolved_title,
        "url": url,
        "content": _clip(extract, max_len=int(max_content_length or 0)),
        "is_disambiguation": is_disambiguation,
    }


async def wikipedia_search(
    query: str,
    lang: str = "zh",
    *,
    sentences: int = 4,
    auto_suggest: bool = True,
    search_results: int = 5,
    max_content_length: int = 4000,
) -> Dict[str, Any]:
    """Search and fetch a Wikipedia page summary/content.

    Returns:
      {
        "success": bool,
        "query": str,
        "lang": str,
        "title": str,
        "url": str,
        "summary": str,
        "content": str,
        "search_hits": string[],
        "disambiguation_options": string[],
        "provider": "wikipedia"
      }
    """

    q = (query or "").strip()
    if not q:
        return {"success": False, "error": "query 不能为空", "provider": "wikipedia"}

    try:
        import wikipedia  # type: ignore
        from wikipedia.exceptions import DisambiguationError, PageError  # type: ignore
    except ImportError as exc:
        # Fallback to the official MediaWiki API (no extra dependency required).
        wiki_lang = (lang or "zh").strip() or "zh"
        base_url = f"https://{wiki_lang}.wikipedia.org/"
        timeout = float(API_TIMEOUT or 120)

        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=min(max(timeout, 10.0), 120.0),
                headers={"User-Agent": "study_ai/1.0 (wikipedia_search)"},
                follow_redirects=True,
            ) as client:
                hits = await _wikipedia_api_search(query=q, search_results=search_results, client=client)
                title = (hits[0] if hits else q).strip()
                disambiguation_options = hits[1:10] if len(hits) > 1 else []

                fetched = await _wikipedia_api_fetch(
                    title=title,
                    max_content_length=max_content_length,
                    client=client,
                )

                # If this is a disambiguation page, try a few alternative hits.
                if fetched.get("success") and fetched.get("is_disambiguation"):
                    for opt in disambiguation_options[:3]:
                        alt = await _wikipedia_api_fetch(
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
                        "lang": wiki_lang,
                        "error": f"Wikipedia API fallback failed: {fetched.get('error') or 'unknown error'}",
                        "search_hits": hits,
                        "disambiguation_options": disambiguation_options,
                        "provider": "wikipedia",
                        "fallback": "mediawiki_api",
                    }

                content = str(fetched.get("content") or "")
                return {
                    "success": True,
                    "query": q,
                    "lang": wiki_lang,
                    "title": str(fetched.get("title") or title),
                    "url": str(fetched.get("url") or ""),
                    "summary": _sentence_summary(content, sentences=sentences),
                    "content": content,
                    "search_hits": hits,
                    "disambiguation_options": disambiguation_options,
                    "provider": "wikipedia",
                    "fallback": "mediawiki_api",
                }
        except (httpx.HTTPError, ValueError, TypeError) as api_exc:
            return {
                "success": False,
                "query": q,
                "lang": wiki_lang,
                "error": f"wikipedia 库不可用: {exc}; MediaWiki API fallback failed: {api_exc}",
                "provider": "wikipedia",
                "fallback": "mediawiki_api",
            }

    def _run() -> Dict[str, Any]:
        try:
            wikipedia.set_lang((lang or "zh").strip() or "zh")
        except Exception:
            # Best-effort: keep default language.
            logger.warning("wikipedia_set_lang_failed", extra={"lang": lang}, exc_info=True)

        hits: List[str] = []
        try:
            hits = list(wikipedia.search(q, results=max(1, min(int(search_results or 5), 10))))  # type: ignore[arg-type]
        except Exception:
            logger.warning("wikipedia_search_hits_failed", extra={"query": q}, exc_info=True)
            hits = []

        title = (hits[0] if hits else q).strip()
        disambiguation_options: List[str] = []

        def _fetch(title_to_fetch: str) -> Dict[str, Any]:
            page = wikipedia.page(  # type: ignore[misc]
                title_to_fetch,
                auto_suggest=bool(auto_suggest),
                redirect=True,
                preload=False,
            )
            summary = wikipedia.summary(  # type: ignore[misc]
                title_to_fetch,
                sentences=max(1, min(int(sentences or 4), 10)),
                auto_suggest=bool(auto_suggest),
                redirect=True,
            )
            content = getattr(page, "content", "") or ""
            url = getattr(page, "url", "") or ""
            return {
                "success": True,
                "query": q,
                "lang": (lang or "zh").strip() or "zh",
                "title": str(getattr(page, "title", "") or title_to_fetch),
                "url": str(url),
                "summary": str(summary or ""),
                "content": _clip(str(content or ""), max_len=int(max_content_length or 0)),
                "search_hits": hits,
                "disambiguation_options": disambiguation_options,
                "provider": "wikipedia",
            }

        try:
            return _fetch(title)
        except DisambiguationError as exc:  # pragma: no cover (network-dependent)
            try:
                disambiguation_options.extend([str(x) for x in (exc.options or []) if str(x).strip()][:10])
            except (AttributeError, TypeError):
                disambiguation_options = []

            # Try a few options as a best-effort fallback.
            for opt in disambiguation_options[:3]:
                try:
                    return _fetch(opt)
                except Exception:
                    logger.warning(
                        "wikipedia_disambiguation_option_fetch_failed",
                        extra={"query": q, "option": opt},
                        exc_info=True,
                    )
                    continue

            return {
                "success": False,
                "query": q,
                "lang": (lang or "zh").strip() or "zh",
                "error": "Wikipedia 结果为歧义页，请提供更具体的关键词。",
                "search_hits": hits,
                "disambiguation_options": disambiguation_options,
                "provider": "wikipedia",
            }
        except PageError:  # pragma: no cover (network-dependent)
            return {
                "success": False,
                "query": q,
                "lang": (lang or "zh").strip() or "zh",
                "error": "未找到对应的 Wikipedia 词条。",
                "search_hits": hits,
                "disambiguation_options": disambiguation_options,
                "provider": "wikipedia",
            }
        except Exception as exc:  # pragma: no cover (network-dependent)
            logger.warning("wikipedia_query_failed", extra={"query": q}, exc_info=True)
            return {
                "success": False,
                "query": q,
                "lang": (lang or "zh").strip() or "zh",
                "error": f"Wikipedia 查询失败: {exc}",
                "search_hits": hits,
                "disambiguation_options": disambiguation_options,
                "provider": "wikipedia",
            }

    return await _to_thread(_run)
