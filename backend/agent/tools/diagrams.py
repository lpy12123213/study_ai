from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.agent.types import CompressedContext


class DiagramToolsMixin:
    async def _tool_draw_svg_diagram(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Render an SVG diagram and persist it under `.local/media/generated/`.

        Args:
            spec: dict - SVG diagram spec (see `backend/core/svg_diagram.py`)
            alt: str (optional) - used in returned Markdown image tag

        Returns:
            {
              "success": bool,
              "media_id": str,
              "filename": str,
              "url": str,
              "markdown": str,
              "bytes": int
            }
        """

        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "diagram").strip() or "diagram"
        if not spec:
            return {"success": False, "error": "spec 不能为空"}

        from backend.core.svg_diagram import render_svg_diagram

        svg = render_svg_diagram(spec)
        svg_bytes = (svg or "").encode("utf-8")

        import hashlib

        media_id = hashlib.sha256(svg_bytes).hexdigest()
        filename = f"{media_id}.svg"

        repo_root = Path(__file__).resolve().parents[3]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        try:
            if not out_path.exists():
                out_path.write_bytes(svg_bytes)
        except Exception as exc:
            return {"success": False, "error": str(exc), "filename": filename}

        url = f"/api/media/generated/{filename}"
        markdown = f"![{alt}]({url})"
        return {
            "success": True,
            "media_id": media_id,
            "filename": filename,
            "url": url,
            "markdown": markdown,
            "bytes": len(svg_bytes),
        }

    async def _tool_draw_diagram(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "diagram").strip() or "diagram"
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

        from backend.core.plot_tools import render_schematic

        try:
            png_bytes = render_schematic(spec)
        except Exception as exc:
            return {"success": False, "error": str(exc), "knowledge_point": kp}

        import hashlib

        media_id = hashlib.sha256(png_bytes).hexdigest()
        filename = f"{media_id}.png"

        repo_root = Path(__file__).resolve().parents[3]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        try:
            if not out_path.exists():
                out_path.write_bytes(png_bytes)
        except Exception as exc:
            return {"success": False, "error": str(exc), "filename": filename, "knowledge_point": kp}

        url = f"/api/media/generated/{filename}"
        markdown = f"![{alt}]({url})"
        diagram = {
            "knowledge_point": kp,
            "kind": "draw_diagram",
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
            pass

        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": media_id,
            "filename": filename,
            "url": url,
            "markdown": markdown,
            "bytes": len(png_bytes),
        }

