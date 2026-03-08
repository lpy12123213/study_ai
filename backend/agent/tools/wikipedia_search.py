from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from backend.agent.types import CompressedContext


class WikipediaToolsMixin:
    async def _tool_wikipedia_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Wikipedia 百科检索（按拆分后的知识点批量查询）。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        lang = str(args.get("lang") or "zh").strip() or "zh"
        sentences = int(args.get("sentences") or 4)
        sentences = max(1, min(sentences, 10))
        max_content_length = int(args.get("max_content_length") or 2000)
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

        from backend.mcp.wikipedia_search import wikipedia_search as _wiki

        async def _lookup_one(point: str) -> Dict[str, Any]:
            query = f"{subject} {point}".strip() if subject and subject not in point else point
            res = await _wiki(
                query=query,
                lang=lang,
                sentences=sentences,
                auto_suggest=True,
                search_results=5,
                max_content_length=max_content_length,
            )
            payload = res if isinstance(res, dict) else {"success": False, "error": "invalid wikipedia response"}
            payload = dict(payload)
            payload["knowledge_point"] = point
            payload["query"] = query
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
                        "provider": "wikipedia",
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {"topic": topic, "subject": subject, "lang": lang, "items": items}
