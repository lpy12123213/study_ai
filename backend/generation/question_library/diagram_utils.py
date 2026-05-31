from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.core.logging_utils import get_logger
from backend.media.diagram_cache import canonical_spec_hash, lookup as cache_lookup, record as cache_record
from backend.media.diagram_source import write_source_sidecar
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes
from backend.shared.diagrams.static_render import (
    asy_tools_missing_hint,
    graphviz_tools_missing_hint,
    render_asy_to_svg_bytes,
    render_graphviz_to_svg_bytes,
    render_tikz_to_svg_bytes,
    tikz_tools_missing_hint,
)
from backend.shared.project_paths import resolve_repo_root

logger = get_logger(__name__)
_REPO_ROOT = resolve_repo_root()


def _user_scoped_spec_hash(kind: str, *, user_id: str, payload: Any) -> str:
    return canonical_spec_hash(kind, {"user_id": str(user_id or "").strip() or "anonymous", "payload": payload})


def _tikz_missing_hint() -> str:
    return tikz_tools_missing_hint()


def _asy_missing_hint() -> str:
    return asy_tools_missing_hint()


def _make_cache_result(
    *, entry: Dict[str, Any], kind: str, alt: str
) -> Dict[str, Any]:
    url = str(entry.get("url") or "").strip()
    filename = str(entry.get("filename") or "").strip()
    alt_safe = str(alt or "diagram").strip() or "diagram"
    return {
        "success": True,
        "kind": kind,
        "url": url,
        "markdown": f"![{alt_safe}]({url})" if url else "",
        "filename": filename,
        "media_id": filename.split(".")[0] if "." in filename else filename,
        "bytes": int(entry.get("bytes") or 0),
        "cached": True,
    }


async def _publish_and_record(
    *,
    spec_hash: str,
    kind: str,
    payload_bytes: bytes,
    user_id: str,
    ext: str,
    mime_type: str,
    alt: str,
    source: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    published = await publish_generated_bytes(
        payload_bytes,
        user_id=user_id,
        ext=ext,
        file_type="image",
        mime_type=mime_type,
        ttl_s=default_generated_media_ttl_s(),
    )
    url = str(published.get("url") or "").strip()
    filename = str(published.get("filename") or "").strip()
    alt_safe = str(alt or "diagram").strip() or "diagram"
    if spec_hash and filename and url:
        await cache_record(
            spec_hash,
            filename=filename,
            url=url,
            kind=kind,
            mime_type=mime_type,
            bytes_size=int(published.get("bytes") or len(payload_bytes)),
        )
    # Persist the generator inputs so an "edit this diagram" flow can reconstruct
    # them later without DB schema changes. Best-effort: failures are silently dropped.
    if filename and source is not None:
        write_source_sidecar(filename=filename, kind=kind, source=source, alt=alt_safe)
    return {
        "success": True,
        "kind": kind,
        "url": url,
        "markdown": f"![{alt_safe}]({url})" if url else "",
        "filename": filename,
        "media_id": str(published.get("sha256") or "").strip(),
        "bytes": int(published.get("bytes") or len(payload_bytes)),
        "cached": False,
    }


async def render_svg_to_url(
    *,
    spec: Dict[str, Any],
    user_id: str,
    alt: str = "diagram",
) -> Dict[str, Any]:
    """Render an SVG diagram spec to a published URL (no CompressedContext dependency)."""

    from backend.core.svg_diagram import render_svg_diagram

    uid = str(user_id or "").strip() or "anonymous"
    spec_clean = spec if isinstance(spec, dict) else {}
    spec_hash = _user_scoped_spec_hash("svg_diagram", user_id=uid, payload=spec_clean)
    cached = await cache_lookup(spec_hash)
    if cached:
        return _make_cache_result(entry=cached, kind="svg", alt=alt)

    svg = render_svg_diagram(spec_clean)
    svg_bytes = (svg or "").encode("utf-8", errors="ignore")
    return await _publish_and_record(
        spec_hash=spec_hash,
        kind="svg",
        payload_bytes=svg_bytes,
        user_id=uid,
        ext=".svg",
        mime_type="image/svg+xml",
        alt=alt,
        source={"spec": spec_clean},
    )


async def render_schematic_to_url(
    *,
    spec: Dict[str, Any],
    user_id: str,
    alt: str = "diagram",
) -> Dict[str, Any]:
    """Render a Matplotlib schematic spec to a published SVG (default) or PNG URL."""

    from backend.core.plot_tools import render_schematic_with_meta

    uid = str(user_id or "").strip() or "anonymous"
    spec_clean = spec if isinstance(spec, dict) else {}
    spec_hash = _user_scoped_spec_hash("schematic", user_id=uid, payload=spec_clean)
    cached = await cache_lookup(spec_hash)
    if cached:
        return _make_cache_result(entry=cached, kind="schematic", alt=alt)

    try:
        res = render_schematic_with_meta(spec_clean)
    except Exception as exc:
        logger.exception("question_library_diagram_render_failed")
        return {"success": False, "error": str(exc)}

    return await _publish_and_record(
        spec_hash=spec_hash,
        kind="schematic",
        payload_bytes=bytes(res.get("image_bytes") or b""),
        user_id=uid,
        ext=str(res.get("image_ext") or ".png"),
        mime_type=str(res.get("image_mime") or "image/png"),
        alt=alt,
        source={"spec": spec_clean},
    )


async def render_matplotlib_2d_to_url(
    *,
    spec: Dict[str, Any],
    user_id: str,
    alt: str = "plot",
) -> Dict[str, Any]:
    """Render a 2D Matplotlib plot (functions / curves) to a published URL."""

    from backend.core.plot_tools import render_2d_plot_with_meta

    uid = str(user_id or "").strip() or "anonymous"
    spec_clean = spec if isinstance(spec, dict) else {}
    spec_hash = _user_scoped_spec_hash("matplotlib_2d", user_id=uid, payload=spec_clean)
    cached = await cache_lookup(spec_hash)
    if cached:
        return _make_cache_result(entry=cached, kind="matplotlib_2d", alt=alt)

    try:
        res = render_2d_plot_with_meta(spec_clean)
    except (RuntimeError, TypeError, ValueError) as exc:
        return {"success": False, "error": str(exc)}
    if not res.get("success"):
        return {"success": False, "error": str(res.get("error") or "plot_render_failed"), "warnings": res.get("warnings") or []}

    return await _publish_and_record(
        spec_hash=spec_hash,
        kind="matplotlib_2d",
        payload_bytes=bytes(res.get("image_bytes") or b""),
        user_id=uid,
        ext=str(res.get("image_ext") or ".svg"),
        mime_type=str(res.get("image_mime") or "image/svg+xml"),
        alt=alt,
        source={"spec": spec_clean},
    )


async def render_matplotlib_3d_to_url(
    *,
    spec: Dict[str, Any],
    user_id: str,
    alt: str = "plot",
) -> Dict[str, Any]:
    """Render a 3D Matplotlib surface plot to a published URL."""

    from backend.core.plot_tools import render_3d_plot_with_meta

    uid = str(user_id or "").strip() or "anonymous"
    spec_clean = spec if isinstance(spec, dict) else {}
    spec_hash = _user_scoped_spec_hash("matplotlib_3d", user_id=uid, payload=spec_clean)
    cached = await cache_lookup(spec_hash)
    if cached:
        return _make_cache_result(entry=cached, kind="matplotlib_3d", alt=alt)

    try:
        res = render_3d_plot_with_meta(spec_clean)
    except (RuntimeError, TypeError, ValueError) as exc:
        return {"success": False, "error": str(exc)}
    if not res.get("success"):
        return {"success": False, "error": str(res.get("error") or "plot_render_failed")}

    return await _publish_and_record(
        spec_hash=spec_hash,
        kind="matplotlib_3d",
        payload_bytes=bytes(res.get("image_bytes") or b""),
        user_id=uid,
        ext=str(res.get("image_ext") or ".svg"),
        mime_type=str(res.get("image_mime") or "image/svg+xml"),
        alt=alt,
        source={"spec": spec_clean},
    )


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

    spec_hash = _user_scoped_spec_hash("tikz", user_id=uid, payload={"tikz": code, "preamble": str(preamble or "")})
    cached = await cache_lookup(spec_hash)
    if cached:
        return _make_cache_result(entry=cached, kind="tikz", alt=alt)

    res = render_tikz_to_svg_bytes(tikz=code, preamble=str(preamble or ""), timeout_s=timeout_s, repo_root=_REPO_ROOT)
    if not bool(res.get("success")):
        out = dict(res)
        out.setdefault("hint", _tikz_missing_hint())
        return out

    return await _publish_and_record(
        spec_hash=spec_hash,
        kind="tikz",
        payload_bytes=bytes(res.get("svg_bytes") or b""),
        user_id=uid,
        ext=".svg",
        mime_type="image/svg+xml",
        alt=alt,
        source={"code": code, "preamble": str(preamble or "")},
    )


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

    spec_hash = _user_scoped_spec_hash("asy", user_id=uid, payload={"asy": code})
    cached = await cache_lookup(spec_hash)
    if cached:
        return _make_cache_result(entry=cached, kind="asy", alt=alt)

    res = render_asy_to_svg_bytes(asy=code, timeout_s=timeout_s, repo_root=_REPO_ROOT)
    if not bool(res.get("success")):
        out = dict(res)
        out.setdefault("hint", _asy_missing_hint())
        return out

    return await _publish_and_record(
        spec_hash=spec_hash,
        kind="asy",
        payload_bytes=bytes(res.get("svg_bytes") or b""),
        user_id=uid,
        ext=".svg",
        mime_type="image/svg+xml",
        alt=alt,
        source={"code": code},
    )


async def render_chemistry_to_url(
    *,
    expression: str,
    user_id: str,
    alt: str = "化学方程式",
    timeout_s: float = 240.0,
) -> Dict[str, Any]:
    """Render a chemistry expression (`\\ce{...}` / mhchem syntax) to an SVG URL.

    Wraps the expression in a TikZ-standalone preamble that loads `mhchem`.
    Accepts either bare mhchem syntax (e.g. `2H2 + O2 -> 2H2O`) or a full
    `\\ce{...}` block. Output is centered black-on-white vector text.
    """

    expr = str(expression or "").strip()
    if not expr:
        return {"success": False, "error": "expression_empty"}

    # Auto-wrap bare expressions in \ce{...}.
    if "\\ce{" not in expr and "$" not in expr:
        ce_expr = "\\ce{" + expr + "}"
    else:
        ce_expr = expr

    preamble = (
        r"\usepackage[version=4]{mhchem}" + "\n"
        r"\usepackage{amsmath}"
    )
    # Use a math-mode tikznode so mhchem renders correctly inside standalone.
    tikz_body = (
        r"\node[inner sep=4pt] {$\displaystyle " + ce_expr + r"$};"
    )

    uid = str(user_id or "").strip() or "anonymous"
    # Cache on canonicalized expression within each user so generated-media
    # authorization metadata stays aligned with the returned URL.
    spec_hash = _user_scoped_spec_hash("chemistry", user_id=uid, payload={"ce": ce_expr})
    cached = await cache_lookup(spec_hash)
    if cached:
        return _make_cache_result(entry=cached, kind="chemistry", alt=alt)

    repo_root = Path(__file__).resolve().parents[2]
    res = render_tikz_to_svg_bytes(tikz=tikz_body, preamble=preamble, timeout_s=timeout_s, repo_root=repo_root)
    if not bool(res.get("success")):
        out = dict(res)
        out.setdefault("hint", "化学方程式渲染需要 mhchem 包（TeX Live/MiKTeX 默认含）+ xelatex + dvisvgm。")
        return out

    return await _publish_and_record(
        spec_hash=spec_hash,
        kind="chemistry",
        payload_bytes=bytes(res.get("svg_bytes") or b""),
        user_id=uid,
        ext=".svg",
        mime_type="image/svg+xml",
        alt=alt,
        source={"expression": expr, "ce_expr": ce_expr},
    )


async def render_circuit_to_url(
    *,
    circuit_code: str,
    user_id: str,
    alt: str = "电路图",
    timeout_s: float = 240.0,
) -> Dict[str, Any]:
    """Render a circuitikz circuit description to an SVG URL.

    Input is a circuit body (lines inside `\\begin{circuitikz}` / `\\end{circuitikz}`).
    If the caller passes a full `\\begin{circuitikz}...\\end{circuitikz}` block, it
    is detected and used verbatim. The renderer loads the `circuitikz` package and
    routes through xelatex + dvisvgm.
    """

    body = str(circuit_code or "").strip()
    if not body:
        return {"success": False, "error": "circuit_empty"}

    if "\\begin{circuitikz}" in body:
        # Caller supplied the full environment; embed it inside a tikzpicture-free standalone.
        # We treat the entire body as the tikz input by stripping the outer tikzpicture wrapper.
        # static_render._ensure_tikzpicture only adds the wrapper if absent, but we need a
        # circuitikz wrapper instead. Use the body directly inside the document.
        tikz_body = body
        # Hack: dvisvgm pipeline expects tikzpicture; circuitikz inherits, so wrap an outer tikz around it.
        if "\\begin{tikzpicture" not in tikz_body:
            tikz_body = "\\begin{tikzpicture}\n" + tikz_body + "\n\\end{tikzpicture}"
    else:
        # Bare body inside an implicit circuitikz environment.
        tikz_body = "\\begin{circuitikz}\n" + body + "\n\\end{circuitikz}"

    preamble = r"\usepackage{circuitikz}"

    uid = str(user_id or "").strip() or "anonymous"
    spec_hash = _user_scoped_spec_hash("circuit", user_id=uid, payload={"body": tikz_body})
    cached = await cache_lookup(spec_hash)
    if cached:
        return _make_cache_result(entry=cached, kind="circuit", alt=alt)

    repo_root = Path(__file__).resolve().parents[2]
    res = render_tikz_to_svg_bytes(tikz=tikz_body, preamble=preamble, timeout_s=timeout_s, repo_root=repo_root)
    if not bool(res.get("success")):
        out = dict(res)
        out.setdefault("hint", "电路图渲染需要 circuitikz 包（TeX Live/MiKTeX 默认含）+ xelatex + dvisvgm。")
        return out

    return await _publish_and_record(
        spec_hash=spec_hash,
        kind="circuit",
        payload_bytes=bytes(res.get("svg_bytes") or b""),
        user_id=uid,
        ext=".svg",
        mime_type="image/svg+xml",
        alt=alt,
        source={"body": body, "wrapped": tikz_body},
    )


async def render_graphviz_to_url(
    *,
    dot_code: str,
    user_id: str,
    alt: str = "流程图",
    engine: str = "dot",
    timeout_s: float = 60.0,
) -> Dict[str, Any]:
    """Render Graphviz DOT source to an SVG URL via `dot -Tsvg`."""

    code = str(dot_code or "").strip()
    if not code:
        return {"success": False, "error": "dot_empty"}

    uid = str(user_id or "").strip() or "anonymous"
    spec_hash = _user_scoped_spec_hash("graphviz", user_id=uid, payload={"dot": code, "engine": engine})
    cached = await cache_lookup(spec_hash)
    if cached:
        return _make_cache_result(entry=cached, kind="graphviz", alt=alt)

    res = render_graphviz_to_svg_bytes(dot_code=code, engine=engine, timeout_s=timeout_s)
    if not bool(res.get("success")):
        out = dict(res)
        out.setdefault("hint", graphviz_tools_missing_hint())
        return out

    return await _publish_and_record(
        spec_hash=spec_hash,
        kind="graphviz",
        payload_bytes=bytes(res.get("svg_bytes") or b""),
        user_id=uid,
        ext=".svg",
        mime_type="image/svg+xml",
        alt=alt,
        source={"dot": code, "engine": engine},
    )
