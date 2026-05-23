from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Dict, List
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from backend.agent.tools.utils.text_utils import _remove_ui_noise
from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


class BrowseWebPagesToolsMixin:
    async def _tool_browse_web_pages(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Browse and extract readable text from top web-search results for each knowledge point.

        Best-effort "browseuse" behavior:
        - Uses prior `web_search_knowledge` outputs in working_memory to pick URLs
        - Fetches pages via httpx and extracts visible text using BeautifulSoup
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        top_k = int(args.get("top_k") or 2)
        top_k = max(1, min(top_k, 5))
        max_chars = int(args.get("max_chars") or 8000)
        max_chars = max(800, min(max_chars, 30000))
        timeout_s = float(args.get("timeout_s") or 18)
        timeout_s = max(5.0, min(timeout_s, 60.0))

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

        def _map_by_point(blob: Any) -> Dict[str, Dict[str, Any]]:
            if not isinstance(blob, dict):
                return {}
            items = blob.get("items")
            if isinstance(items, list):
                mapped: Dict[str, Dict[str, Any]] = {}
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if kp:
                        mapped[kp] = it
                return mapped
            kp = str(blob.get("knowledge_point") or "").strip()
            if kp:
                return {kp: blob}  # type: ignore[return-value]
            return {}

        web_map = _map_by_point(ctx.working_memory.get("web_search_knowledge"))
        gh_map = _map_by_point(ctx.working_memory.get("github_search"))
        se_map = _map_by_point(ctx.working_memory.get("stackexchange_search"))
        wiki_map = _map_by_point(ctx.working_memory.get("wikipedia_search"))
        mw_map = _map_by_point(ctx.working_memory.get("mediawiki_search"))

        now = time.time()
        ttl_raw = args.get("cache_ttl_s") or os.getenv("STUDY_MATERIALS_BROWSE_CACHE_TTL_S") or "86400"
        try:
            cache_ttl_s = float(ttl_raw)
        except (TypeError, ValueError):
            cache_ttl_s = 86400.0
        cache_ttl_s = max(30.0, min(cache_ttl_s, 60.0 * 60.0 * 24.0 * 7.0))

        max_entries_raw = (
            args.get("cache_max_entries") or os.getenv("STUDY_MATERIALS_BROWSE_CACHE_MAX_ENTRIES") or "256"
        )
        try:
            cache_max_entries = int(max_entries_raw)
        except (TypeError, ValueError):
            cache_max_entries = 256
        cache_max_entries = max(50, min(cache_max_entries, 2000))

        inline_min_chars_raw = (
            args.get("inline_min_chars") or os.getenv("STUDY_MATERIALS_BROWSE_INLINE_MIN_CHARS") or "900"
        )
        try:
            inline_min_chars = int(inline_min_chars_raw)
        except (TypeError, ValueError):
            inline_min_chars = 900
        inline_min_chars = max(200, min(inline_min_chars, 3000))

        cache_blob = ctx.working_memory.get("browse_web_pages_cache")
        cache_blob = dict(cache_blob) if isinstance(cache_blob, dict) else {}
        cache_entries = cache_blob.get("entries")
        cache_entries = dict(cache_entries) if isinstance(cache_entries, dict) else {}
        cache_updates: Dict[str, Dict[str, Any]] = {}
        cache_stats = {"hits": 0, "writes": 0, "inline": 0}

        def _cache_key(url: str) -> str:
            raw = (url or "").strip()
            if not raw:
                return ""
            try:
                parsed = urlparse(raw)
                # Avoid fragment keys exploding the cache.
                parsed = parsed._replace(fragment="")
                return parsed.geturl().strip().lower()
            except ValueError:
                return raw.lower()

        def _get_cached_page(url: str) -> Dict[str, Any]:
            key = _cache_key(url)
            if not key:
                return {}
            ent = cache_entries.get(key)
            if not isinstance(ent, dict):
                return {}
            try:
                ts = float(ent.get("ts") or 0.0)
            except (TypeError, ValueError):
                ts = 0.0
            if ts and cache_ttl_s > 0 and (now - ts) > cache_ttl_s:
                return {}
            page = ent.get("page")
            if not isinstance(page, dict) or not page.get("success"):
                return {}
            out = dict(page)
            out["cache_hit"] = True
            return out

        def _extract_urls(results: Any) -> List[str]:
            if not isinstance(results, list):
                return []
            urls: List[str] = []
            seen: set[str] = set()
            for r in results:
                if not isinstance(r, dict):
                    continue
                u = str(r.get("url") or r.get("link") or "").strip()
                if not u or not u.startswith(("http://", "https://")):
                    continue
                key = u.lower()
                if key in seen:
                    continue
                seen.add(key)
                urls.append(u)
                if len(urls) >= max(10, top_k * 3):
                    break
            return urls

        def _normalize_url_for_fetch(u: str) -> str:
            raw = (u or "").strip()
            if not raw:
                return ""
            try:
                parsed = urlparse(raw)
                host = (parsed.netloc or "").lower()
                if host == "link.zhihu.com":
                    qs = parse_qs(parsed.query or "")
                    target = qs.get("target", [""])[0]
                    if target:
                        return unquote(str(target))
                return raw
            except ValueError:
                return raw

        def _is_zhihu_url(u: str) -> bool:
            try:
                host = (urlparse(u).netloc or "").lower()
            except ValueError:
                return False
            return host == "zhihu.com" or host.endswith(".zhihu.com")

        async def _fetch_one(url: str, *, client: httpx.AsyncClient) -> Dict[str, Any]:
            url = _normalize_url_for_fetch(url) or url

            if _is_zhihu_url(url):
                cookies = (os.getenv("ZHIHU_COOKIES") or "").strip()
                try:
                    from backend.integrations.mcp.search.zhihu import ZhihuFetcher
                except ImportError as exc:
                    return {"url": url, "success": False, "error": f"zhihu_fetcher not available: {exc}"}

                try:
                    zh_timeout = int(max(5.0, min(float(timeout_s), 60.0)))
                except (TypeError, ValueError):
                    zh_timeout = 30

                fetcher = ZhihuFetcher(cookies=cookies, timeout_seconds=zh_timeout)
                res = await fetcher.fetch(url)
                payload = res.to_dict()

                if not bool(payload.get("success")):
                    out: Dict[str, Any] = {
                        "url": url,
                        "success": False,
                        "provider": "zhihu",
                        "error": str(payload.get("error") or "fetch_failed"),
                        "title": str(payload.get("title") or "").strip(),
                        "author": str(payload.get("author") or "").strip(),
                        "date": str(payload.get("date") or "").strip(),
                        "zhihu_type": str(payload.get("type") or "").strip(),
                    }
                    out = {k: v for k, v in out.items() if v not in ("", None)}
                    if out.get("error") == "cookies_required" and not cookies:
                        out["note"] = "需要登录态：请在环境变量或 .env 配置 ZHIHU_COOKIES"
                    return out

                text = str(payload.get("content_markdown") or "").strip()
                if len(text) > max_chars:
                    text = text[: max_chars - 1].rstrip() + "…"

                out = {
                    "url": url,
                    "success": True,
                    "provider": "zhihu",
                    "content_type": "text/markdown",
                    "zhihu_type": str(payload.get("type") or "").strip(),
                    "title": str(payload.get("title") or "").strip(),
                    "author": str(payload.get("author") or "").strip(),
                    "date": str(payload.get("date") or "").strip(),
                    "chars": len(text),
                    "text": text,
                }
                return {k: v for k, v in out.items() if v not in ("", None)}

            # Skip non-HTML-ish resources.
            if url.lower().endswith((".pdf", ".zip", ".rar", ".7z")):
                return {"url": url, "success": False, "error": "unsupported file type"}
            try:
                resp = await client.get(url)
                ct = str(resp.headers.get("content-type") or "").lower()
                if "application/pdf" in ct:
                    return {"url": url, "success": False, "error": "pdf not supported", "content_type": ct}
                html = resp.text or ""
            except httpx.HTTPError as exc:
                return {"url": url, "success": False, "error": str(exc)}

            try:
                from bs4 import BeautifulSoup  # type: ignore
            except ImportError as exc:
                return {"url": url, "success": False, "error": f"beautifulsoup4 not available: {exc}"}

            try:
                soup = BeautifulSoup(html, "lxml")
                for tag in soup(
                    [
                        "script",
                        "style",
                        "noscript",
                        "svg",
                        "canvas",
                        "iframe",
                        "form",
                        "input",
                        "button",
                        "textarea",
                        "select",
                        "option",
                    ]
                ):
                    try:
                        tag.decompose()
                    except Exception:
                        logger.warning("browse_decompose_tag_failed", exc_info=True)
                for tag in soup(["header", "footer", "nav", "aside"]):
                    try:
                        tag.decompose()
                    except Exception:
                        logger.warning("browse_decompose_tag_failed", exc_info=True)
                try:
                    for tag in soup.find_all(
                        attrs={"role": re.compile(r"^(navigation|banner|contentinfo|complementary)$", re.I)}
                    ):
                        try:
                            tag.decompose()
                        except Exception:
                            logger.warning("browse_decompose_tag_failed", exc_info=True)
                except Exception:
                    logger.warning("browse_find_role_tags_failed", exc_info=True)

                title = ""
                try:
                    title = str(soup.title.string or "").strip() if soup.title else ""
                except AttributeError:
                    title = ""

                body = soup.body or soup
                candidates: List[Any] = []

                def _add(node: Any) -> None:
                    if node is None:
                        return
                    if node not in candidates:
                        candidates.append(node)

                _add(body.find("article"))
                _add(body.find("main"))
                _add(body.find(id="mw-content-text"))
                _add(body.find(id="bodyContent"))
                _add(body.find(id="content"))
                _add(body.find(id="main"))
                try:
                    _add(
                        body.find(
                            "div", class_=re.compile(r"(content|main|article|post|entry|text|lemma|summary)", re.I)
                        )
                    )
                except Exception:
                    logger.warning("browse_find_candidate_failed", exc_info=True)
                try:
                    _add(body.find("div", id=re.compile(r"(content|main|article|post|entry|text)", re.I)))
                except Exception:
                    logger.warning("browse_find_candidate_failed", exc_info=True)

                def _len_text(node: Any) -> int:
                    try:
                        return len(node.get_text(" ", strip=True))
                    except (AttributeError, TypeError, ValueError):
                        return 0

                root = max(candidates, key=_len_text, default=body)
                extracted = root.get_text("\n", strip=True)
                extracted = _remove_ui_noise(extracted)
                if len(extracted) > max_chars:
                    extracted = extracted[: max_chars - 1].rstrip() + "…"

                return {
                    "url": url,
                    "success": True,
                    "title": title,
                    "content_type": ct,
                    "chars": len(extracted),
                    "text": extracted,
                }
            except Exception as exc:
                logger.warning("browse_parse_failed", extra={"url": url}, exc_info=True)
                return {"url": url, "success": False, "error": f"parse failed: {exc}"}

        concurrency = int(args.get("concurrency") or 2)
        concurrency = max(1, min(concurrency, 4))
        sem = asyncio.Semaphore(concurrency)
        zhihu_sem = asyncio.Semaphore(min(2, concurrency))

        async def _guarded_fetch(url: str, *, client: httpx.AsyncClient) -> Dict[str, Any]:
            normalized = _normalize_url_for_fetch(url) or url
            cached = _get_cached_page(normalized)
            if cached:
                try:
                    cache_stats["hits"] += 1
                except (KeyError, TypeError, ValueError):
                    logger.warning("browse_cache_stats_update_failed", exc_info=True)
                return cached
            async with sem:
                if _is_zhihu_url(normalized):
                    async with zhihu_sem:
                        out = await _fetch_one(normalized, client=client)
                else:
                    out = await _fetch_one(normalized, client=client)

            if isinstance(out, dict) and out.get("success"):
                key = _cache_key(str(out.get("url") or normalized))
                if key:
                    cache_updates[key] = {"ts": now, "page": dict(out)}
                    try:
                        cache_stats["writes"] += 1
                    except (KeyError, TypeError, ValueError):
                        logger.warning("browse_cache_stats_update_failed", exc_info=True)
            return out

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }

        items: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=timeout_s, headers=headers, follow_redirects=True) as client:
            for point in points:
                urls: List[str] = []
                seen: set[str] = set()

                def _add_urls(more: List[str]) -> None:
                    for u in more or []:
                        key = (u or "").strip().lower()
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        urls.append(u)

                web = web_map.get(point) or {}

                # Reuse `web_search_knowledge` results that already include body text (e.g. Exa include_text)
                # to avoid redundant network fetches.
                inline_pages_by_key: Dict[str, Dict[str, Any]] = {}
                web_results = web.get("results")
                if isinstance(web_results, list):
                    for r in web_results:
                        if not isinstance(r, dict):
                            continue
                        u = str(r.get("url") or r.get("link") or "").strip()
                        if not u.startswith(("http://", "https://")):
                            continue
                        normalized_u = _normalize_url_for_fetch(u) or u
                        key = _cache_key(normalized_u)
                        if not key or key in inline_pages_by_key:
                            continue
                        text = str(r.get("text") or "").strip()
                        if len(text) < inline_min_chars:
                            continue
                        cleaned = _remove_ui_noise(text)
                        if len(cleaned) > max_chars:
                            cleaned = cleaned[: max_chars - 1].rstrip() + "鈥?"
                        title = str(r.get("title") or "").strip()
                        page = {
                            "url": normalized_u,
                            "success": True,
                            "provider": "web_search",
                            "content_type": "text/plain",
                            "title": title,
                            "chars": len(cleaned),
                            "text": cleaned,
                            "inline_text": True,
                        }
                        page = {k: v for k, v in page.items() if v not in ("", None)}
                        inline_pages_by_key[key] = page
                        cache_updates[key] = {"ts": now, "page": dict(page)}
                        try:
                            cache_stats["inline"] += 1
                            cache_stats["writes"] += 1
                        except (KeyError, TypeError, ValueError):
                            logger.warning("browse_cache_stats_update_failed", exc_info=True)

                _add_urls(_extract_urls(web.get("results")))

                se = se_map.get(point) or {}
                _add_urls(_extract_urls(se.get("results")))

                gh = gh_map.get(point) or {}
                _add_urls(_extract_urls(gh.get("results")))

                wiki = wiki_map.get(point) or {}
                wiki_url = str(wiki.get("url") or "").strip()
                if wiki_url.startswith(("http://", "https://")):
                    _add_urls([wiki_url])

                mw = mw_map.get(point) or {}
                mw_url = str(mw.get("url") or "").strip()
                if mw_url.startswith(("http://", "https://")):
                    _add_urls([mw_url])

                urls = urls[: max(0, top_k)]

                if not urls:
                    items.append(
                        {
                            "knowledge_point": point,
                            "success": False,
                            "top_k": top_k,
                            "max_chars": max_chars,
                            "pages": [],
                            "error": "no urls from web/github/stackexchange/wiki sources",
                        }
                    )
                    continue

                to_fetch: List[str] = []
                for u in urls:
                    normalized_u = _normalize_url_for_fetch(u) or u
                    key = _cache_key(normalized_u)
                    if key and key in inline_pages_by_key:
                        continue
                    to_fetch.append(u)

                fetched_pages: List[Dict[str, Any]] = []
                if to_fetch:
                    fetched_pages = await asyncio.gather(*[_guarded_fetch(u, client=client) for u in to_fetch])

                fetched_iter = iter(fetched_pages)
                pages: List[Dict[str, Any]] = []
                for u in urls:
                    normalized_u = _normalize_url_for_fetch(u) or u
                    key = _cache_key(normalized_u)
                    if key and key in inline_pages_by_key:
                        pages.append(dict(inline_pages_by_key[key]))
                        continue
                    try:
                        pages.append(next(fetched_iter))
                    except StopIteration:
                        pages.append({"url": normalized_u, "success": False, "error": "fetch_missing"})
                ok = [p for p in pages if isinstance(p, dict) and p.get("success")]
                items.append(
                    {
                        "knowledge_point": point,
                        "success": len(ok) > 0,
                        "top_k": top_k,
                        "max_chars": max_chars,
                        "source": "web_search_knowledge",
                        "pages": pages,
                    }
                )

        cache_size = 0
        try:
            merged = dict(cache_entries)
            merged.update(cache_updates)

            if cache_ttl_s > 0:
                for k in list(merged.keys()):
                    ent = merged.get(k)
                    if not isinstance(ent, dict):
                        merged.pop(k, None)
                        continue
                    try:
                        ts = float(ent.get("ts") or 0.0)
                    except (TypeError, ValueError):
                        ts = 0.0
                    if ts and (now - ts) > cache_ttl_s:
                        merged.pop(k, None)

            if len(merged) > cache_max_entries:
                by_ts = sorted(
                    merged.items(),
                    key=lambda kv: float(kv[1].get("ts") or 0.0) if isinstance(kv[1], dict) else 0.0,
                )
                drop = max(0, len(by_ts) - cache_max_entries)
                for k, _ in by_ts[:drop]:
                    merged.pop(k, None)

            cache_blob["entries"] = merged
            cache_blob["ttl_s"] = cache_ttl_s
            cache_blob["max_entries"] = cache_max_entries
            cache_blob["updated_at"] = now
            ctx.working_memory["browse_web_pages_cache"] = cache_blob
            cache_size = len(merged)
        except Exception:
            logger.warning("browse_cache_update_failed", exc_info=True)
            cache_size = 0

        cache_info = {
            "entries": cache_size,
            "hits": int(cache_stats.get("hits") or 0),
            "writes": int(cache_stats.get("writes") or 0),
            "inline": int(cache_stats.get("inline") or 0),
            "ttl_s": cache_ttl_s,
        }

        return {
            "topic": topic,
            "subject": subject,
            "top_k": top_k,
            "max_chars": max_chars,
            "items": items,
            "cache": cache_info,
        }
