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
from typing import Any, Dict, List, Optional


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
    except Exception as exc:
        return {
            "success": False,
            "query": q,
            "lang": lang,
            "error": f"wikipedia 库不可用: {exc}. 请安装 requirements.txt 中的 wikipedia 依赖后重试。",
            "provider": "wikipedia",
        }

    def _run() -> Dict[str, Any]:
        try:
            wikipedia.set_lang((lang or "zh").strip() or "zh")
        except Exception:
            # Best-effort: keep default language.
            pass

        hits: List[str] = []
        try:
            hits = list(wikipedia.search(q, results=max(1, min(int(search_results or 5), 10))))  # type: ignore[arg-type]
        except Exception:
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
            except Exception:
                disambiguation_options = []

            # Try a few options as a best-effort fallback.
            for opt in disambiguation_options[:3]:
                try:
                    return _fetch(opt)
                except Exception:
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

