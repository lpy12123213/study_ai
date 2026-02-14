from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from backend.agent.types import CompressedContext


class MediaWikiToolsMixin:
    async def _tool_mediawiki_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """MediaWiki 百科检索（可用于 Wikipedia/Wikibooks/ProofWiki 等 MediaWiki 站点）。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        # Base URL building:
        # - if base_url provided: use it directly
        # - else: build from project + lang, e.g. https://zh.wikibooks.org/
        base_url = str(args.get("base_url") or "").strip()
        project = str(args.get("project") or "").strip().lower()
        lang = str(args.get("lang") or "zh").strip() or "zh"

        if not base_url:
            if project in {"wikipedia", "wikibooks", "wikiversity", "wikisource", "wiktionary"}:
                domain = "wikipedia.org" if project == "wikipedia" else f"{project}.org"
                base_url = f"https://{lang}.{domain}/"
            elif project:
                base_url = str(project)

        sentences = int(args.get("sentences") or 5)
        sentences = max(1, min(sentences, 10))
        search_results = int(args.get("search_results") or 5)
        search_results = max(1, min(search_results, 10))
        max_content_length = int(args.get("max_content_length") or 6000)
        max_content_length = max(200, min(max_content_length, 8000))

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

        existing_by_kp: Dict[str, Dict[str, Any]] = {}
        try:
            prev_blob = ctx.working_memory.get("mediawiki_search")
            if isinstance(prev_blob, dict) and isinstance(prev_blob.get("items"), list):
                for it in prev_blob.get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if kp:
                        existing_by_kp[kp] = it
        except Exception:
            existing_by_kp = {}

        from backend.mcp.mediawiki_search import mediawiki_search

        async def _lookup_one(point: str) -> Dict[str, Any]:
            query = f"{subject} {point}".strip() if subject and subject not in point else point
            prev = existing_by_kp.get(point) or {}
            prev_query = str(prev.get("query") or "").strip()
            prev_base = str(prev.get("base_url") or "").strip()
            if (
                prev_query == query
                and prev_base
                and prev_base == base_url
                and str(prev.get("content") or prev.get("summary") or "").strip()
            ):
                cached = dict(prev)
                cached["success"] = True
                cached["cache_hit"] = True
                return cached
            res = await mediawiki_search(
                query=query,
                base_url=base_url,
                sentences=sentences,
                search_results=search_results,
                max_content_length=max_content_length,
            )
            payload = res if isinstance(res, dict) else {"success": False, "error": "invalid mediawiki response"}
            payload["knowledge_point"] = point
            payload["provider"] = payload.get("provider") or "mediawiki_api"
            return payload

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _lookup_one(point)
                except Exception as exc:  # pragma: no cover
                    return {
                        "success": False,
                        "knowledge_point": point,
                        "query": point,
                        "error": str(exc),
                        "provider": "mediawiki_api",
                        "base_url": base_url,
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "base_url": base_url,
            "project": project,
            "lang": lang,
            "sentences": sentences,
            "search_results": search_results,
            "max_content_length": max_content_length,
            "items": items,
        }

