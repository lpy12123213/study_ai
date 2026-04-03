from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes

logger = get_logger(__name__)


def _tikz_missing_hint() -> str:
    return (
        "TikZ rendering requires both `xelatex` and `dvisvgm` on PATH. "
        "Install a TeX distribution (MiKTeX/TeX Live) that provides them, or use the SVG/Matplotlib backends."
    )


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

    missing: List[str] = []
    if shutil.which("xelatex") is None:
        missing.append("xelatex")
    if shutil.which("dvisvgm") is None:
        missing.append("dvisvgm")
    if missing:
        return {"success": False, "error": "tikz_tools_missing", "missing": missing, "hint": _tikz_missing_hint()}

    if "\\begin{tikzpicture" not in code:
        code = "\\begin{tikzpicture}\n" + code + "\n\\end{tikzpicture}"

    preamble = str(preamble or "").strip()
    tex_lines = [
        r"\\documentclass[tikz]{standalone}",
        r"\\usepackage{tikz}",
    ]
    if preamble:
        tex_lines.append(preamble)
    tex_lines.extend([r"\\begin{document}", code, r"\\end{document}", ""])
    tex = "\n".join(tex_lines)

    repo_root = Path(__file__).resolve().parents[2]
    build_dir = (repo_root / ".local" / "latex_build" / uuid.uuid4().hex[:12]).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)

    tex_path = build_dir / "main.tex"
    tex_path.write_text(tex, encoding="utf-8")

    timeout_s = float(timeout_s or 240.0)
    timeout_s = max(30.0, min(timeout_s, 60.0 * 20.0))

    cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "main.tex"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(build_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        return {"success": False, "error": f"latex_engine_not_found: {exc}", "hint": _tikz_missing_hint()}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "latex_compile_timeout"}

    if proc.returncode != 0:
        stderr = (getattr(proc, "stderr", "") or "").strip()
        stdout = (getattr(proc, "stdout", "") or "").strip()
        msg = (stderr or stdout)[-2000:]
        return {"success": False, "error": f"latex_compile_failed: {msg}"}

    pdf_path = build_dir / "main.pdf"
    if not pdf_path.exists():
        return {"success": False, "error": "pdf_missing"}

    svg_path = build_dir / "main.svg"
    dvisvgm_cmd = [
        "dvisvgm",
        "--pdf",
        "--no-fonts",
        "--exact-bbox",
        "-o",
        str(svg_path.name),
        str(pdf_path.name),
    ]

    try:
        proc2 = subprocess.run(
            dvisvgm_cmd,
            cwd=str(build_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        return {"success": False, "error": f"dvisvgm_not_found: {exc}", "hint": _tikz_missing_hint()}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "dvisvgm_timeout"}

    if proc2.returncode != 0 or not svg_path.exists():
        stderr = (getattr(proc2, "stderr", "") or "").strip()
        stdout = (getattr(proc2, "stdout", "") or "").strip()
        msg = (stderr or stdout)[-2000:]
        return {"success": False, "error": f"dvisvgm_failed: {msg}"}

    svg_bytes = svg_path.read_bytes()
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

