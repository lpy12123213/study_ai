from __future__ import annotations

import io
import os
from typing import Any, Dict, List

from backend.core.helpers import get_logger
from backend.core.plot.expression import _PLOT_EVAL_EXCEPTIONS, _safe_eval_expr
from backend.core.plot.parsers import _as_str, _clamp_float, _clamp_int, _iter_list, _parse_range

logger = get_logger(__name__)

def _to_png_bytes(fig: Any, *, dpi: int) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    return buf.getvalue()


def _to_svg_bytes(fig: Any) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    return buf.getvalue()


def _default_plot_format() -> str:
    raw = (os.getenv("STUDY_AI_PLOT_FORMAT") or "").strip().lower()
    if raw in {"svg", "png"}:
        return raw
    return "svg"


def _to_image_bytes(fig: Any, *, dpi: int, fmt: str) -> Dict[str, Any]:
    chosen = (fmt or _default_plot_format()).strip().lower()
    if chosen == "png":
        return {
            "bytes": _to_png_bytes(fig, dpi=dpi),
            "format": "png",
            "ext": ".png",
            "mime": "image/png",
        }
    return {
        "bytes": _to_svg_bytes(fig),
        "format": "svg",
        "ext": ".svg",
        "mime": "image/svg+xml",
    }


def render_2d_plot_with_meta(spec: Dict[str, Any]) -> Dict[str, Any]:
    import numpy as np

    width = _clamp_int(spec.get("width"), default=820, min_value=360, max_value=1600)
    height = _clamp_int(spec.get("height"), default=520, min_value=280, max_value=1200)
    dpi = _clamp_int(spec.get("dpi"), default=150, min_value=72, max_value=240)

    x_min, x_max = _parse_range(spec.get("x_range"), default=(-5.0, 5.0))
    y_range = spec.get("y_range")

    grid = bool(spec.get("grid", True))
    aspect_equal = bool(spec.get("aspect_equal", False))
    title = _as_str(spec.get("title") or "")

    n = _clamp_int(spec.get("num_points"), default=900, min_value=200, max_value=4000)
    x = np.linspace(float(x_min), float(x_max), int(n))

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
    from matplotlib.figure import Figure

    fig = Figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    FigureCanvas(fig)
    ax = fig.add_subplot(111)

    if title:
        ax.set_title(title)

    if grid:
        ax.grid(True, alpha=0.25)

    warnings: List[Dict[str, str]] = []
    rendered_any = False
    curves = [c for c in _iter_list(spec.get("curves")) if isinstance(c, dict)]
    for c in curves:
        expr = _as_str(c.get("expr"))
        if not expr:
            continue
        label = _as_str(c.get("label") or "")
        color = _as_str(c.get("color") or "")
        style = _as_str(c.get("style") or "-") or "-"
        lw = _clamp_float(c.get("linewidth"), default=2.2, min_value=0.6, max_value=6.0)
        try:
            y = _safe_eval_expr(expr, variables={"x": x})
            y = np.asarray(y, dtype=float)
        except _PLOT_EVAL_EXCEPTIONS as exc:
            warnings.append({"kind": "curve", "expr": expr, "reason": str(exc)})
            continue
        if y.shape != x.shape:
            warnings.append({"kind": "curve", "expr": expr, "reason": "shape_mismatch"})
            continue
        mask = np.isfinite(y)
        if not mask.any():
            warnings.append({"kind": "curve", "expr": expr, "reason": "no_finite_points"})
            continue
        ax.plot(x[mask], y[mask], style, color=(color or None), linewidth=lw, label=(label or None))
        rendered_any = True

    implicit_curves = [c for c in _iter_list(spec.get("implicit_curves")) if isinstance(c, dict)]
    if implicit_curves:
        res = _clamp_int(spec.get("implicit_resolution"), default=260, min_value=120, max_value=720)
        y_min, y_max = _parse_range(y_range, default=(-5.0, 5.0)) if y_range is not None else (-5.0, 5.0)
        xs = np.linspace(float(x_min), float(x_max), int(res))
        ys = np.linspace(float(y_min), float(y_max), int(res))
        X, Y = np.meshgrid(xs, ys)
        for c in implicit_curves:
            expr = _as_str(c.get("expr"))
            if not expr:
                continue
            color = _as_str(c.get("color") or "#111827")
            lw = _clamp_float(c.get("linewidth"), default=2.0, min_value=0.6, max_value=6.0)
            try:
                Z = _safe_eval_expr(expr, variables={"x": X, "y": Y})
                Z = np.asarray(Z, dtype=float)
            except _PLOT_EVAL_EXCEPTIONS as exc:
                warnings.append({"kind": "implicit_curve", "expr": expr, "reason": str(exc)})
                continue
            try:
                ax.contour(X, Y, Z, levels=[0.0], colors=[color], linewidths=[lw])
                rendered_any = True
            except (RuntimeError, TypeError, ValueError):
                continue

    vlines = [v for v in _iter_list(spec.get("vlines")) if isinstance(v, (int, float, str, dict))]
    for v in vlines:
        x0 = None
        if isinstance(v, dict):
            x0 = v.get("x")
        else:
            x0 = v
        try:
            xv = float(x0)
        except (TypeError, ValueError):
            continue
        ax.axvline(xv, color="#9ca3af", linewidth=1.3, linestyle="--", alpha=0.9)
        rendered_any = True

    hlines = [v for v in _iter_list(spec.get("hlines")) if isinstance(v, (int, float, str, dict))]
    for v in hlines:
        y0 = None
        if isinstance(v, dict):
            y0 = v.get("y")
        else:
            y0 = v
        try:
            yv = float(y0)
        except (TypeError, ValueError):
            continue
        ax.axhline(yv, color="#9ca3af", linewidth=1.3, linestyle="--", alpha=0.9)
        rendered_any = True

    tangent_lines = [t for t in _iter_list(spec.get("tangent_lines")) if isinstance(t, dict)]
    for t in tangent_lines:
        idx = t.get("curve_index")
        try:
            ci = int(idx)
        except (TypeError, ValueError):
            continue
        if ci < 0 or ci >= len(curves):
            continue
        c = curves[ci]
        expr = _as_str(c.get("expr"))
        if not expr:
            continue
        try:
            x0 = float(t.get("at_x"))
        except (TypeError, ValueError):
            continue

        h = _clamp_float(t.get("h"), default=1e-3, min_value=1e-6, max_value=1.0)
        try:
            y0 = float(_safe_eval_expr(expr, variables={"x": x0}))
            yp = float(_safe_eval_expr(expr, variables={"x": x0 + h}))
            ym = float(_safe_eval_expr(expr, variables={"x": x0 - h}))
        except _PLOT_EVAL_EXCEPTIONS:
            continue
        m = (yp - ym) / (2.0 * h)
        xs = np.array([float(x_min), float(x_max)], dtype=float)
        ys = y0 + m * (xs - x0)
        color = _as_str(t.get("color") or "#ef4444")
        lw = _clamp_float(t.get("linewidth"), default=2.2, min_value=0.6, max_value=6.0)
        ax.plot(xs, ys, "-", color=color, linewidth=lw)
        ax.scatter([x0], [y0], s=20, color=color)
        rendered_any = True

    points = [p for p in _iter_list(spec.get("points")) if isinstance(p, dict)]
    for p in points:
        try:
            px = float(p.get("x"))
            py = float(p.get("y"))
        except (TypeError, ValueError):
            continue
        label = _as_str(p.get("label") or "")
        ax.scatter([px], [py], s=32, color=_as_str(p.get("color") or "#111827"))
        if label:
            ax.text(px, py, f" {label}", fontsize=10)
        rendered_any = True

    annotations = [a for a in _iter_list(spec.get("annotations")) if isinstance(a, dict)]
    for a in annotations:
        text = _as_str(a.get("text") or "")
        if not text:
            continue
        try:
            x0 = float(a.get("x"))
            y0 = float(a.get("y"))
        except (TypeError, ValueError):
            continue
        arrow_to = a.get("arrow_to")
        if isinstance(arrow_to, (list, tuple)) and len(arrow_to) >= 2:
            try:
                tx = float(arrow_to[0])
                ty = float(arrow_to[1])
            except (TypeError, ValueError):
                tx, ty = x0, y0
            ax.annotate(text, xy=(tx, ty), xytext=(x0, y0), arrowprops={"arrowstyle": "->", "lw": 1.3})
        else:
            ax.text(x0, y0, text, fontsize=10)
        rendered_any = True

    ax.set_xlim(float(x_min), float(x_max))
    if y_range is not None:
        y_min, y_max = _parse_range(y_range, default=(-5.0, 5.0))
        ax.set_ylim(float(y_min), float(y_max))

    if aspect_equal:
        ax.set_aspect("equal", adjustable="box")

    if rendered_any and any(_as_str(c.get("label") or "") for c in curves):
        ax.legend(loc="best")

    if not rendered_any:
        return {"success": False, "error": "no_renderable_curves", "warnings": warnings, "png_bytes": b""}

    fmt = (
        (spec.get("image_format") or _default_plot_format()).strip().lower()
        if isinstance(spec.get("image_format"), str)
        else _default_plot_format()
    )
    img = _to_image_bytes(fig, dpi=dpi, fmt=fmt)
    return {
        "success": True,
        "png_bytes": img["bytes"] if img["format"] == "png" else _to_png_bytes(fig, dpi=dpi),
        "image_bytes": img["bytes"],
        "image_format": img["format"],
        "image_ext": img["ext"],
        "image_mime": img["mime"],
        "warnings": warnings,
    }


def render_2d_plot(spec: Dict[str, Any]) -> bytes:
    result = render_2d_plot_with_meta(spec)
    if not result.get("success"):
        raise ValueError(str(result.get("error") or "plot_render_failed"))
    return bytes(result.get("png_bytes") or b"")


def render_3d_plot(spec: Dict[str, Any]) -> bytes:
    import numpy as np

    width = _clamp_int(spec.get("width"), default=860, min_value=420, max_value=1800)
    height = _clamp_int(spec.get("height"), default=620, min_value=320, max_value=1400)
    dpi = _clamp_int(spec.get("dpi"), default=150, min_value=72, max_value=240)

    x_min, x_max = _parse_range(spec.get("x_range"), default=(-5.0, 5.0))
    y_min, y_max = _parse_range(spec.get("y_range"), default=(-5.0, 5.0))

    expr = _as_str(spec.get("expr") or "")
    if not expr:
        raise ValueError("missing_expr")

    n = _clamp_int(spec.get("resolution"), default=80, min_value=25, max_value=220)
    xs = np.linspace(float(x_min), float(x_max), int(n))
    ys = np.linspace(float(y_min), float(y_max), int(n))
    X, Y = np.meshgrid(xs, ys)

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
    from matplotlib.figure import Figure

    fig = Figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    FigureCanvas(fig)

    ax = fig.add_subplot(111, projection="3d")

    try:
        Z = _safe_eval_expr(expr, variables={"x": X, "y": Y})
        Z = np.asarray(Z, dtype=float)
    except _PLOT_EVAL_EXCEPTIONS as exc:
        raise ValueError("eval_failed") from exc

    cmap = _as_str(spec.get("colormap") or "viridis")
    ax.plot_surface(X, Y, Z, cmap=cmap, linewidth=0.0, antialiased=True)

    title = _as_str(spec.get("title") or "")
    if title:
        ax.set_title(title)

    elev = _clamp_float(spec.get("view_elev"), default=28.0, min_value=-89.0, max_value=89.0)
    azim = _clamp_float(spec.get("view_azim"), default=-55.0, min_value=-360.0, max_value=360.0)
    try:
        ax.view_init(elev=float(elev), azim=float(azim))
    except (TypeError, ValueError, RuntimeError):
        logger.warning("plot_view_init_failed", exc_info=True)

    return _to_png_bytes(fig, dpi=dpi)


def render_3d_plot_with_meta(spec: Dict[str, Any]) -> Dict[str, Any]:
    """SVG/PNG-aware variant. Returns image bytes plus format metadata."""

    import numpy as np

    width = _clamp_int(spec.get("width"), default=860, min_value=420, max_value=1800)
    height = _clamp_int(spec.get("height"), default=620, min_value=320, max_value=1400)
    dpi = _clamp_int(spec.get("dpi"), default=150, min_value=72, max_value=240)

    x_min, x_max = _parse_range(spec.get("x_range"), default=(-5.0, 5.0))
    y_min, y_max = _parse_range(spec.get("y_range"), default=(-5.0, 5.0))

    expr = _as_str(spec.get("expr") or "")
    if not expr:
        return {"success": False, "error": "missing_expr"}

    n = _clamp_int(spec.get("resolution"), default=80, min_value=25, max_value=220)
    xs = np.linspace(float(x_min), float(x_max), int(n))
    ys = np.linspace(float(y_min), float(y_max), int(n))
    X, Y = np.meshgrid(xs, ys)

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
    from matplotlib.figure import Figure

    fig = Figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    FigureCanvas(fig)
    ax = fig.add_subplot(111, projection="3d")

    try:
        Z = _safe_eval_expr(expr, variables={"x": X, "y": Y})
        Z = np.asarray(Z, dtype=float)
    except _PLOT_EVAL_EXCEPTIONS as exc:
        return {"success": False, "error": f"eval_failed: {exc}"}

    cmap = _as_str(spec.get("colormap") or "viridis")
    ax.plot_surface(X, Y, Z, cmap=cmap, linewidth=0.0, antialiased=True)

    title = _as_str(spec.get("title") or "")
    if title:
        ax.set_title(title)

    elev = _clamp_float(spec.get("view_elev"), default=28.0, min_value=-89.0, max_value=89.0)
    azim = _clamp_float(spec.get("view_azim"), default=-55.0, min_value=-360.0, max_value=360.0)
    try:
        ax.view_init(elev=float(elev), azim=float(azim))
    except (TypeError, ValueError, RuntimeError):
        logger.warning("plot_view_init_failed", exc_info=True)

    fmt = (
        (spec.get("image_format") or _default_plot_format()).strip().lower()
        if isinstance(spec.get("image_format"), str)
        else _default_plot_format()
    )
    img = _to_image_bytes(fig, dpi=dpi, fmt=fmt)
    return {
        "success": True,
        "image_bytes": img["bytes"],
        "image_format": img["format"],
        "image_ext": img["ext"],
        "image_mime": img["mime"],
    }
