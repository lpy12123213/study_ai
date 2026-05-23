from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


class StackExchangeToolsMixin:
    async def _tool_stackexchange_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """StackExchange 搜索：为每个知识点检索高质量问答解释。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        limit = int(args.get("limit") or 5)
        limit = max(1, min(limit, 10))
        query_hint = str(args.get("query_hint") or "").strip()
        site = str(args.get("site") or "math.stackexchange").strip() or "math.stackexchange"
        include_answers = bool(args.get("include_answers", True))

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
            prev_blob = ctx.working_memory.get("stackexchange_search")
            if isinstance(prev_blob, dict) and isinstance(prev_blob.get("items"), list):
                for it in prev_blob.get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if kp:
                        existing_by_kp[kp] = it
        except (AttributeError, TypeError, ValueError):
            existing_by_kp = {}

        from backend.integrations.mcp.search.stackexchange import stackexchange_search

        async def _search_one(point: str) -> Dict[str, Any]:
            base_query = f"{subject} {point}".strip() if subject and subject not in point else point
            query = base_query
            if query_hint:
                query = f"{query} {query_hint}".strip()

            prev = existing_by_kp.get(point) or {}
            prev_queries = prev.get("queries") if isinstance(prev.get("queries"), list) else []
            prev_results = prev.get("results") if isinstance(prev.get("results"), list) else []
            if (prev.get("query") == query or query in prev_queries) and prev_results:
                cached = dict(prev)
                cached["success"] = True
                cached["cache_hit"] = True
                return cached

            res = await stackexchange_search(
                query=query,
                site=site,
                limit=limit,
                include_answers=include_answers,
                max_question_chars=3200,
                max_answer_chars=3200,
            )
            if not isinstance(res, dict) or not res.get("success"):
                return {
                    "knowledge_point": point,
                    "success": False,
                    "query": query,
                    "site": site,
                    "provider": "stackexchange",
                    "results": [],
                    "error": str((res or {}).get("error") or "stackexchange search failed"),
                }
            return {
                "knowledge_point": point,
                "success": True,
                "query": query,
                "queries": [query],
                "site": site,
                "provider": "stackexchange",
                "results": res.get("results") or [],
            }

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _search_one(point)
                except Exception as exc:  # pragma: no cover
                    logger.exception("stackexchange_search_failed", extra={"knowledge_point": point})
                    return {
                        "knowledge_point": point,
                        "success": False,
                        "query": point,
                        "site": site,
                        "provider": "stackexchange",
                        "results": [],
                        "error": str(exc),
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "site": site,
            "limit": limit,
            "query_hint": query_hint,
            "items": items,
        }
