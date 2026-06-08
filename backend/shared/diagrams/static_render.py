from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def tikz_tools_missing_hint() -> str:
    return (
        "TikZ rendering requires both `xelatex` and `dvisvgm` on PATH. "
        "Install a TeX distribution (MiKTeX/TeX Live) that provides them, "
        "or fall back to the Asymptote backend when TikZ is unavailable."
    )


def asy_tools_missing_hint() -> str:
    return (
        "Asymptote rendering requires `asy` on PATH. "
        "Install Asymptote (often bundled with TeX Live / MiKTeX), "
        "or ensure your TeX distribution includes the `asy` executable."
    )


def graphviz_tools_missing_hint() -> str:
    return (
        "Graphviz rendering requires `dot` on PATH. "
        "Install Graphviz (https://graphviz.org/download/) or apt/brew install graphviz."
    )


def check_graphviz_tools() -> List[str]:
    missing: List[str] = []
    if shutil.which("dot") is None:
        missing.append("dot")
    return missing


def render_graphviz_to_svg_bytes(
    *,
    dot_code: str,
    engine: str = "dot",
    timeout_s: float = 60.0,
) -> Dict[str, Any]:
    """Render Graphviz DOT source to SVG bytes via `dot -Tsvg` (best-effort)."""

    code = str(dot_code or "").strip()
    if not code:
        return {"success": False, "error": "dot_empty"}

    missing = check_graphviz_tools()
    if missing:
        return {"success": False, "error": "graphviz_tools_missing", "missing": missing, "hint": graphviz_tools_missing_hint()}

    eng = (engine or "dot").strip().lower()
    allowed_engines = {"dot", "neato", "fdp", "sfdp", "twopi", "circo"}
    if eng not in allowed_engines:
        eng = "dot"
    timeout = _clamp_timeout_s(timeout_s, default=60.0)
    cmd = [eng, "-Tsvg"]
    try:
        proc = subprocess.run(
            cmd,
            input=code,
            capture_output=True,
            text=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return {"success": False, "error": f"graphviz_not_found: {exc}", "hint": graphviz_tools_missing_hint()}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "graphviz_timeout"}

    if proc.returncode != 0 or not proc.stdout:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        return {"success": False, "error": f"graphviz_failed: {stderr[-1500:] if stderr else 'no_output'}"}

    return {"success": True, "svg_bytes": proc.stdout}


def _repo_root() -> Path:
    # backend/shared/diagrams/static_render.py -> repo root
    return Path(__file__).resolve().parents[3]


def _clamp_timeout_s(timeout_s: float, *, default: float = 240.0) -> float:
    try:
        t = float(timeout_s or 0.0)
    except (TypeError, ValueError):
        t = float(default)
    return max(10.0, min(t, 60.0 * 20.0))


def _ensure_tikzpicture(code: str) -> str:
    if "\\begin{tikzpicture" in code:
        return code
    return "\\begin{tikzpicture}\n" + code + "\n\\end{tikzpicture}"


def build_tikz_standalone_tex(*, tikz: str, preamble: str = "") -> str:
    """Build a minimal standalone TeX document for TikZ compilation."""

    code = _ensure_tikzpicture(str(tikz or "").strip())
    extra = str(preamble or "").strip()

    # Keep the default libraries conservative: avoid heavy packages like pgfplots
    # unless explicitly requested by the caller via `preamble`.
    tex_lines: List[str] = [
        r"\documentclass[tikz]{standalone}",
        r"\usepackage{tikz}",
        r"\usetikzlibrary{arrows.meta,calc,angles,quotes,positioning,decorations.markings,decorations.pathmorphing,patterns}",
    ]
    if extra:
        tex_lines.append(extra)
    tex_lines.extend([r"\begin{document}", code, r"\end{document}", ""])
    return "\n".join(tex_lines)


def check_tikz_tools() -> List[str]:
    missing: List[str] = []
    if shutil.which("xelatex") is None:
        missing.append("xelatex")
    if shutil.which("dvisvgm") is None:
        missing.append("dvisvgm")
    return missing


def check_asy_tools() -> List[str]:
    missing: List[str] = []
    if shutil.which("asy") is None:
        missing.append("asy")
    return missing


def render_tikz_to_svg_bytes(
    *,
    tikz: str,
    preamble: str = "",
    timeout_s: float = 240.0,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Render TikZ code to SVG bytes using xelatex + dvisvgm (best-effort)."""

    code = str(tikz or "").strip()
    if not code:
        return {"success": False, "error": "tikz_empty"}

    missing = check_tikz_tools()
    if missing:
        return {"success": False, "error": "tikz_tools_missing", "missing": missing, "hint": tikz_tools_missing_hint()}

    root = (repo_root or _repo_root()).resolve()
    build_dir = (root / ".local" / "latex_build" / uuid.uuid4().hex[:12]).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)

    try:
        tex = build_tikz_standalone_tex(tikz=code, preamble=preamble)
        (build_dir / "main.tex").write_text(tex, encoding="utf-8")

        timeout = _clamp_timeout_s(timeout_s, default=240.0)
        cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "main.tex"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(build_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            return {"success": False, "error": f"latex_engine_not_found: {exc}", "hint": tikz_tools_missing_hint()}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "latex_compile_timeout"}

        if proc.returncode != 0:
            stderr = (getattr(proc, "stderr", "") or "").strip()
            stdout = (getattr(proc, "stdout", "") or "").strip()
            msg = (stderr or stdout)[-2000:]
            return {"success": False, "error": f"latex_compile_failed: {msg}"}

        pdf_path = build_dir / "main.pdf"
        if not pdf_path.exists() or not pdf_path.is_file():
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
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            return {"success": False, "error": f"dvisvgm_not_found: {exc}", "hint": tikz_tools_missing_hint()}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "dvisvgm_timeout"}

        if proc2.returncode != 0 or not svg_path.exists() or not svg_path.is_file():
            stderr = (getattr(proc2, "stderr", "") or "").strip()
            stdout = (getattr(proc2, "stdout", "") or "").strip()
            msg = (stderr or stdout)[-2000:]
            return {"success": False, "error": f"dvisvgm_failed: {msg}"}

        return {"success": True, "svg_bytes": svg_path.read_bytes()}
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def render_asy_to_svg_bytes(
    *,
    asy: str,
    timeout_s: float = 240.0,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Render Asymptote code to SVG bytes using `asy -f svg` (best-effort)."""

    code = str(asy or "").strip()
    if not code:
        return {"success": False, "error": "asy_empty"}

    missing = check_asy_tools()
    if missing:
        return {"success": False, "error": "asy_tools_missing", "missing": missing, "hint": asy_tools_missing_hint()}

    root = (repo_root or _repo_root()).resolve()
    build_dir = (root / ".local" / "asy_build" / uuid.uuid4().hex[:12]).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)

    asy_path = build_dir / "main.asy"
    try:
        asy_path.write_text(code, encoding="utf-8")

        timeout = _clamp_timeout_s(timeout_s, default=240.0)
        # Use a stable base name without extension; Asymptote will append the format suffix.
        cmd = ["asy", "-f", "svg", "-o", "main", str(asy_path.name)]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(build_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            return {"success": False, "error": f"asy_not_found: {exc}", "hint": asy_tools_missing_hint()}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "asy_compile_timeout"}

        if proc.returncode != 0:
            stderr = (getattr(proc, "stderr", "") or "").strip()
            stdout = (getattr(proc, "stdout", "") or "").strip()
            msg = (stderr or stdout)[-2000:]
            return {"success": False, "error": f"asy_compile_failed: {msg}"}

        svg_path = build_dir / "main.svg"
        if not svg_path.exists() or not svg_path.is_file():
            # Some Asymptote versions may output a different basename; pick the newest SVG.
            candidates = [p for p in build_dir.glob("*.svg") if p.is_file()]
            if not candidates:
                return {"success": False, "error": "svg_missing"}
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            svg_path = candidates[0]

        return {"success": True, "svg_bytes": svg_path.read_bytes()}
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)
