from __future__ import annotations

from typing import Any, Dict, Optional

from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.generation.question_library.diagram_utils import (
    render_matplotlib_2d_to_url,
    render_matplotlib_3d_to_url,
)

logger = get_logger(__name__)


def _store_diagram_in_working_memory(ctx: CompressedContext, kp: str, diagram: Dict[str, Any]) -> None:
    try:
        blob = ctx.working_memory.get("diagrams")
        if not isinstance(blob, dict):
            blob = {}
        items = blob.get("items")
        if not isinstance(items, list):
            items = []
        kp_item: Optional[Dict[str, Any]] = None
        for it in items:
            if not isinstance(it, dict):
                continue
            if str(it.get("knowledge_point") or "").strip() == kp:
                kp_item = it
                break
        if kp_item is None:
            kp_item = {"knowledge_point": kp, "diagrams": []}
            items.append(kp_item)
        dlist = kp_item.get("diagrams")
        if not isinstance(dlist, list):
            dlist = []
        filename = str(diagram.get("filename") or "").strip()
        if filename and not any(isinstance(d, dict) and str(d.get("filename") or "").strip() == filename for d in dlist):
            dlist.append(diagram)
        kp_item["diagrams"] = [d for d in dlist if isinstance(d, dict)][-20:]
        blob["items"] = [x for x in items if isinstance(x, dict)]
        ctx.working_memory["diagrams"] = blob
    except (AttributeError, TypeError, ValueError):
        logger.debug("plot_store_working_memory_failed", exc_info=True)


def _resolve_kp(args: Dict[str, Any], ctx: CompressedContext) -> str:
    kp = str(args.get("knowledge_point") or "").strip()
    if not kp:
        kps = args.get("knowledge_points")
        if isinstance(kps, list) and kps:
            kp = str(kps[0] or "").strip()
    if not kp:
        kp = str(ctx.current_task or "").strip()
    return kp


class PlotToolsMixin:
    async def _tool_plot_function(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "plot").strip() or "plot"
        caption = str(args.get("caption") or spec.get("caption") or "").strip()
        kp = _resolve_kp(args, ctx)

        if not spec:
            return {"success": False, "error": "spec 不能为空", "knowledge_point": kp}

        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await render_matplotlib_2d_to_url(spec=spec, user_id=user_id, alt=alt)
        if not published.get("success"):
            return {
                "success": False,
                "error": str(published.get("error") or "plot_render_failed"),
                "warnings": published.get("warnings") or [],
                "knowledge_point": kp,
            }

        url = str(published.get("url") or "")
        filename = str(published.get("filename") or "")
        diagram = {
            "knowledge_point": kp,
            "kind": "plot_function",
            "url": url,
            "markdown": str(published.get("markdown") or ""),
            "filename": filename,
            "media_id": str(published.get("media_id") or ""),
            "caption": caption,
            "cached": bool(published.get("cached")),
        }
        _store_diagram_in_working_memory(ctx, kp, diagram)

        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": diagram["media_id"],
            "filename": filename,
            "url": url,
            "markdown": diagram["markdown"],
            "bytes": int(published.get("bytes") or 0),
            "cached": bool(published.get("cached")),
        }

    async def _tool_plot_3d(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "plot").strip() or "plot"
        caption = str(args.get("caption") or spec.get("caption") or "").strip()
        kp = _resolve_kp(args, ctx)

        if not spec:
            return {"success": False, "error": "spec 不能为空", "knowledge_point": kp}

        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await render_matplotlib_3d_to_url(spec=spec, user_id=user_id, alt=alt)
        if not published.get("success"):
            return {
                "success": False,
                "error": str(published.get("error") or "plot_render_failed"),
                "knowledge_point": kp,
            }

        url = str(published.get("url") or "")
        filename = str(published.get("filename") or "")
        diagram = {
            "knowledge_point": kp,
            "kind": "plot_3d",
            "url": url,
            "markdown": str(published.get("markdown") or ""),
            "filename": filename,
            "media_id": str(published.get("media_id") or ""),
            "caption": caption,
            "cached": bool(published.get("cached")),
        }
        _store_diagram_in_working_memory(ctx, kp, diagram)

        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": diagram["media_id"],
            "filename": filename,
            "url": url,
            "markdown": diagram["markdown"],
            "bytes": int(published.get("bytes") or 0),
            "cached": bool(published.get("cached")),
        }
