from __future__ import annotations

from typing import Any, Dict, List

from backend.agent.types import CompressedContext


class AggregationToolsMixin:
    async def _tool_aggregate_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """聚合：拆分结果 + Web 搜索 + 题库检索（可选：百科/网页正文/问答/GitHub）。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

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

        def _map_by_point(blob: Any) -> Dict[str, Any]:
            if not isinstance(blob, dict):
                return {}
            items = blob.get("items")
            if isinstance(items, list):
                mapped: Dict[str, Any] = {}
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if not kp:
                        continue
                    mapped[kp] = it
                return mapped
            # Single-result style payload
            kp = str(blob.get("knowledge_point") or "").strip()
            if kp:
                return {kp: blob}
            return {}

        web_map = _map_by_point(ctx.working_memory.get("web_search_knowledge"))
        browse_map = _map_by_point(ctx.working_memory.get("browse_web_pages"))
        wiki_map = _map_by_point(ctx.working_memory.get("wikipedia_search"))
        mw_map = _map_by_point(ctx.working_memory.get("mediawiki_search"))
        gh_map = _map_by_point(ctx.working_memory.get("github_search"))
        se_map = _map_by_point(ctx.working_memory.get("stackexchange_search"))
        q_map = _map_by_point(ctx.working_memory.get("search_questions_by_knowledge"))

        aggregated_items: List[Dict[str, Any]] = []
        for kp in points:
            aggregated_items.append(
                {
                    "knowledge_point": kp,
                    "wikipedia": wiki_map.get(kp) or {},
                    "mediawiki": mw_map.get(kp) or {},
                    "web_search": web_map.get(kp) or {},
                    "web_pages": browse_map.get(kp) or {},
                    "github": gh_map.get(kp) or {},
                    "stackexchange": se_map.get(kp) or {},
                    "questions": q_map.get(kp) or {},
                }
            )

        summary = {
            "topic": topic,
            "subject": subject,
            "knowledge_points": points,
            "items": aggregated_items,
            "counts": {
                "knowledge_points": len(points),
                "web": len([x for x in web_map.values() if isinstance(x, dict) and (x.get("results") or [])]),
                "pages": len([x for x in browse_map.values() if isinstance(x, dict) and (x.get("pages") or [])]),
                "wiki": len(
                    [x for x in wiki_map.values() if isinstance(x, dict) and (x.get("summary") or x.get("content"))]
                ),
                "mediawiki": len(
                    [x for x in mw_map.values() if isinstance(x, dict) and (x.get("summary") or x.get("content"))]
                ),
                "github": len([x for x in gh_map.values() if isinstance(x, dict) and (x.get("results") or [])]),
                "stackexchange": len([x for x in se_map.values() if isinstance(x, dict) and (x.get("results") or [])]),
                "questions": len(
                    [
                        x
                        for x in q_map.values()
                        if isinstance(x, dict) and (x.get("questions") or x.get("examples") or x.get("exercises"))
                    ]
                ),
            },
        }
        ctx.working_memory["aggregated"] = summary
        return summary
