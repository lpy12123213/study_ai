from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from backend.agent.types import CompressedContext


class GithubSearchToolsMixin:
    async def _tool_github_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """GitHub 搜索：为每个知识点检索可能的高质量笔记/资料仓库。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        limit = int(args.get("limit") or 5)
        limit = max(1, min(limit, 10))
        query_hint = str(args.get("query_hint") or "").strip()
        sort = str(args.get("sort") or "stars").strip() or "stars"
        order = str(args.get("order") or "desc").strip() or "desc"
        include_readme = bool(args.get("include_readme", False))
        readme_limit = int(args.get("readme_limit") or (2 if include_readme else 0))
        readme_limit = max(0, min(readme_limit, 3))
        readme_max_chars = int(args.get("readme_max_chars") or 3000)
        readme_max_chars = max(200, min(readme_max_chars, 10000))

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
            prev_blob = ctx.working_memory.get("github_search")
            if isinstance(prev_blob, dict) and isinstance(prev_blob.get("items"), list):
                for it in prev_blob.get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if kp:
                        existing_by_kp[kp] = it
        except Exception:
            existing_by_kp = {}

        from backend.mcp.github_search import github_fetch_readme, github_search_repositories

        async def _search_one(point: str) -> Dict[str, Any]:
            base_query = f"{subject} {point}".strip() if subject and subject not in point else point
            query = base_query
            if query_hint:
                query = f"{query} {query_hint}".strip()

            # Bias toward repositories with documentation.
            gh_query = f"{query} in:readme"

            prev = existing_by_kp.get(point) or {}
            prev_queries = prev.get("queries") if isinstance(prev.get("queries"), list) else []
            prev_results = prev.get("results") if isinstance(prev.get("results"), list) else []
            if (prev.get("query") == gh_query or gh_query in prev_queries) and prev_results:
                # If README enrichment is requested, ensure it already exists for the top few repos.
                if include_readme and readme_limit > 0:
                    need_readme = False
                    for r in prev_results[:readme_limit]:
                        if not isinstance(r, dict):
                            continue
                        if not str(r.get("readme_excerpt") or "").strip():
                            need_readme = True
                            break
                    if not need_readme:
                        cached = dict(prev)
                        cached["success"] = True
                        cached["cache_hit"] = True
                        return cached
                else:
                    cached = dict(prev)
                    cached["success"] = True
                    cached["cache_hit"] = True
                    return cached

            res = await github_search_repositories(gh_query, limit=limit, sort=sort, order=order)
            if not isinstance(res, dict) or not res.get("success"):
                return {
                    "knowledge_point": point,
                    "success": False,
                    "query": gh_query,
                    "provider": "github",
                    "results": [],
                    "error": str((res or {}).get("error") or "github search failed"),
                    "note": str((res or {}).get("note") or ""),
                }

            results = res.get("results") or []
            if include_readme and readme_limit > 0 and isinstance(results, list) and results:
                enriched: List[Dict[str, Any]] = []
                for r in results:
                    enriched.append(r if isinstance(r, dict) else {})
                for r in enriched[:readme_limit]:
                    full_name = str(r.get("full_name") or "").strip()
                    if not full_name:
                        continue
                    rd = await github_fetch_readme(full_name, max_chars=readme_max_chars)
                    if isinstance(rd, dict) and rd.get("success") and rd.get("readme"):
                        r["readme_excerpt"] = str(rd.get("readme") or "")
                results = enriched

            out: Dict[str, Any] = {
                "knowledge_point": point,
                "success": True,
                "query": gh_query,
                "queries": [gh_query],
                "provider": "github",
                "results": results,
                "total_count": res.get("total_count") or 0,
            }
            note = str(res.get("note") or "").strip()
            if note:
                out["note"] = note
            return out

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _search_one(point)
                except Exception as exc:  # pragma: no cover
                    return {
                        "knowledge_point": point,
                        "success": False,
                        "query": point,
                        "provider": "github",
                        "results": [],
                        "error": str(exc),
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "limit": limit,
            "query_hint": query_hint,
            "items": items,
        }
