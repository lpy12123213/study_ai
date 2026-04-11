from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes
from backend.shared.diagrams.static_render import (
    asy_tools_missing_hint,
    render_asy_to_svg_bytes,
    render_tikz_to_svg_bytes,
    tikz_tools_missing_hint,
)

logger = get_logger(__name__)


def _tikz_missing_hint() -> str:
    # Backwards compatible name: used by older callers and error payloads.
    return tikz_tools_missing_hint()


def _asy_missing_hint() -> str:
    return asy_tools_missing_hint()


async def render_svg_to_url(
    *,
    spec: Dict[str, Any],
    user_id: str,
    alt: str = "diagram",
) -> Dict[str, Any]:
    """Render an SVG diagram spec to a published URL (no CompressedContext dependency)."""

    from backend.core.svg_diagram import render_svg_diagram

    uid = str(user_id or "").strip() or "anonymous"
    svg = render_svg_diagram(spec if isinstance(spec, dict) else {})
    svg_bytes = (svg or "").encode("utf-8", errors="ignore")
    published = await publish_generated_bytes(
        svg_bytes,
        user_id=uid,
        ext=".svg",
        file_type="image",
        mime_type="image/svg+xml",
        ttl_s=default_generated_media_ttl_s(),
    )
    url = str(published.get("url") or "").strip()
    return {
        "success": True,
        "kind": "svg",
        "url": url,
        "markdown": f"![{str(alt or 'diagram').strip() or 'diagram'}]({url})" if url else "",
        "filename": str(published.get("filename") or "").strip(),
        "media_id": str(published.get("sha256") or "").strip(),
        "bytes": int(published.get("bytes") or len(svg_bytes)),
    }


async def render_schematic_to_url(
    *,
    spec: Dict[str, Any],
    user_id: str,
    alt: str = "diagram",
) -> Dict[str, Any]:
    """Render a Matplotlib schematic spec to a published PNG URL."""

    from backend.core.plot_tools import render_schematic

    uid = str(user_id or "").strip() or "anonymous"
    try:
        png_bytes = render_schematic(spec if isinstance(spec, dict) else {})
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    published = await publish_generated_bytes(
        png_bytes,
        user_id=uid,
        ext=".png",
        file_type="image",
        mime_type="image/png",
        ttl_s=default_generated_media_ttl_s(),
    )
    url = str(published.get("url") or "").strip()
    return {
        "success": True,
        "kind": "schematic",
        "url": url,
        "markdown": f"![{str(alt or 'diagram').strip() or 'diagram'}]({url})" if url else "",
        "filename": str(published.get("filename") or "").strip(),
        "media_id": str(published.get("sha256") or "").strip(),
        "bytes": int(published.get("bytes") or len(png_bytes)),
    }


async def render_tikz_to_url(
    *,
    tikz: str,
    user_id: str,
    alt: str = "diagram",
    preamble: str = "",
    timeout_s: float = 240.0,
) -> Dict[str, Any]:
    """Render TikZ code to a published SVG URL using xelatex + dvisvgm."""

    uid = str(user_id or "").strip() or "anonymous"
    code = str(tikz or "").strip()
    if not code:
        return {"success": False, "error": "tikz_empty"}

    repo_root = Path(__file__).resolve().parents[2]
    res = render_tikz_to_svg_bytes(tikz=code, preamble=str(preamble or ""), timeout_s=timeout_s, repo_root=repo_root)
    if not bool(res.get("success")):
        out = dict(res)
        out.setdefault("hint", _tikz_missing_hint())
        return out

    svg_bytes = bytes(res.get("svg_bytes") or b"")
    published = await publish_generated_bytes(
        svg_bytes,
        user_id=uid,
        ext=".svg",
        file_type="image",
        mime_type="image/svg+xml",
        ttl_s=default_generated_media_ttl_s(),
    )
    url = str(published.get("url") or "").strip()
    return {
        "success": True,
        "kind": "tikz",
        "url": url,
        "markdown": f"![{str(alt or 'diagram').strip() or 'diagram'}]({url})" if url else "",
        "filename": str(published.get("filename") or "").strip(),
        "media_id": str(published.get("sha256") or "").strip(),
        "bytes": int(published.get("bytes") or len(svg_bytes)),
    }


async def render_asy_to_url(
    *,
    asy: str,
    user_id: str,
    alt: str = "diagram",
    timeout_s: float = 240.0,
) -> Dict[str, Any]:
    """Render Asymptote code to a published SVG URL using `asy -f svg`."""

    uid = str(user_id or "").strip() or "anonymous"
    code = str(asy or "").strip()
    if not code:
        return {"success": False, "error": "asy_empty"}

    repo_root = Path(__file__).resolve().parents[2]
    res = render_asy_to_svg_bytes(asy=code, timeout_s=timeout_s, repo_root=repo_root)
    if not bool(res.get("success")):
        out = dict(res)
        out.setdefault("hint", _asy_missing_hint())
        return out

    svg_bytes = bytes(res.get("svg_bytes") or b"")
    published = await publish_generated_bytes(
        svg_bytes,
        user_id=uid,
        ext=".svg",
        file_type="image",
        mime_type="image/svg+xml",
        ttl_s=default_generated_media_ttl_s(),
    )
    url = str(published.get("url") or "").strip()
    return {
        "success": True,
        "kind": "asy",
        "url": url,
        "markdown": f"![{str(alt or 'diagram').strip() or 'diagram'}]({url})" if url else "",
        "filename": str(published.get("filename") or "").strip(),
        "media_id": str(published.get("sha256") or "").strip(),
        "bytes": int(published.get("bytes") or len(svg_bytes)),
    }
