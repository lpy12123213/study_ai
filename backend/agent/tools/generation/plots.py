from __future__ import annotations

from typing import Any, Dict, Optional

from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes

logger = get_logger(__name__)


class PlotToolsMixin:
    async def _tool_plot_function(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "plot").strip() or "plot"
        caption = str(args.get("caption") or spec.get("caption") or "").strip()

        kp = str(args.get("knowledge_point") or "").strip()
        if not kp:
            kps = args.get("knowledge_points")
            if isinstance(kps, list) and kps:
                kp = str(kps[0] or "").strip()
        if not kp:
            kp = str(ctx.current_task or "").strip()

        if not spec:
            return {"success": False, "error": "spec 不能为空", "knowledge_point": kp}

        from backend.core.plot_tools import render_2d_plot_with_meta

        try:
            plot_result = render_2d_plot_with_meta(spec)
        except Exception as exc:
            return {"success": False, "error": str(exc), "knowledge_point": kp}

        if not plot_result.get("success"):
            return {
                "success": False,
                "error": str(plot_result.get("error") or "plot_render_failed"),
                "warnings": plot_result.get("warnings") or [],
                "knowledge_point": kp,
            }

        png_bytes = bytes(plot_result.get("png_bytes") or b"")
        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await publish_generated_bytes(
            png_bytes,
            user_id=user_id,
            ext=".png",
            file_type="image",
            mime_type="image/png",
            ttl_s=default_generated_media_ttl_s(),
        )

        media_id = str(published.get("sha256") or "")
        filename = str(published.get("filename") or "")
        url = str(published.get("url") or "")
        markdown = f"![{alt}]({url})"
        diagram = {
            "knowledge_point": kp,
            "kind": "plot_function",
            "url": url,
            "markdown": markdown,
            "filename": filename,
            "media_id": media_id,
            "caption": caption,
        }

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
            if not any(isinstance(d, dict) and str(d.get("filename") or "").strip() == filename for d in dlist):
                dlist.append(diagram)
            kp_item["diagrams"] = [d for d in dlist if isinstance(d, dict)][-20:]
            blob["items"] = [x for x in items if isinstance(x, dict)]
            ctx.working_memory["diagrams"] = blob
        except Exception:
            logger.debug("plot_store_working_memory_failed", exc_info=True)

        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": media_id,
            "filename": filename,
            "url": url,
            "markdown": markdown,
            "bytes": int(published.get("bytes") or len(png_bytes)),
            "warnings": plot_result.get("warnings") or [],
        }

    async def _tool_plot_3d(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "plot").strip() or "plot"
        caption = str(args.get("caption") or spec.get("caption") or "").strip()

        kp = str(args.get("knowledge_point") or "").strip()
        if not kp:
            kps = args.get("knowledge_points")
            if isinstance(kps, list) and kps:
                kp = str(kps[0] or "").strip()
        if not kp:
            kp = str(ctx.current_task or "").strip()

        if not spec:
            return {"success": False, "error": "spec 不能为空", "knowledge_point": kp}

        from backend.core.plot_tools import render_3d_plot

        try:
            png_bytes = render_3d_plot(spec)
        except Exception as exc:
            return {"success": False, "error": str(exc), "knowledge_point": kp}
        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await publish_generated_bytes(
            png_bytes,
            user_id=user_id,
            ext=".png",
            file_type="image",
            mime_type="image/png",
            ttl_s=default_generated_media_ttl_s(),
        )

        media_id = str(published.get("sha256") or "")
        filename = str(published.get("filename") or "")
        url = str(published.get("url") or "")
        markdown = f"![{alt}]({url})"
        diagram = {
            "knowledge_point": kp,
            "kind": "plot_3d",
            "url": url,
            "markdown": markdown,
            "filename": filename,
            "media_id": media_id,
            "caption": caption,
        }

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
            if not any(isinstance(d, dict) and str(d.get("filename") or "").strip() == filename for d in dlist):
                dlist.append(diagram)
            kp_item["diagrams"] = [d for d in dlist if isinstance(d, dict)][-20:]
            blob["items"] = [x for x in items if isinstance(x, dict)]
            ctx.working_memory["diagrams"] = blob
        except Exception:
            logger.debug("plot_store_working_memory_failed", exc_info=True)

        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": media_id,
            "filename": filename,
            "url": url,
            "markdown": markdown,
            "bytes": int(published.get("bytes") or len(png_bytes)),
        }
