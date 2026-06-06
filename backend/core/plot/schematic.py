from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from backend.core.plot.charts import _default_plot_format, _to_png_bytes, _to_svg_bytes
from backend.core.plot.geometry import _schematic_auto_ranges
from backend.core.plot.parsers import _as_str, _clamp_float, _clamp_int, _iter_list, _parse_range
from backend.core.plot.schematic_elements import draw_schematic_elements
from backend.core.plot.schematic_primitives import arrow_label_position, plot_path


def render_schematic(spec: Dict[str, Any]) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
    from matplotlib.figure import Figure
    from matplotlib.patches import Arc, Circle, FancyArrowPatch, Rectangle

    width = _clamp_int(spec.get("width"), default=900, min_value=420, max_value=2000)
    height = _clamp_int(spec.get("height"), default=520, min_value=320, max_value=1400)
    dpi = _clamp_int(spec.get("dpi"), default=150, min_value=72, max_value=240)

    fig = Figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    FigureCanvas(fig)
    ax = fig.add_subplot(111)

    auto_x_range, auto_y_range = _schematic_auto_ranges(spec)
    x_min, x_max = _parse_range(spec.get("x_range"), default=auto_x_range)
    y_min, y_max = _parse_range(spec.get("y_range"), default=auto_y_range)
    ax.set_xlim(float(x_min), float(x_max))
    ax.set_ylim(float(y_min), float(y_max))
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    objects = [o for o in _iter_list(spec.get("objects")) if isinstance(o, dict)]
    centers: Dict[str, Tuple[float, float]] = {}
    rendered_any = False
    for o in objects:
        oid = _as_str(o.get("id") or "")
        shape = _as_str(o.get("shape") or "block")
        pos = o.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) >= 2:
            cx = _clamp_float(pos[0], default=0.0, min_value=-1e6, max_value=1e6)
            cy = _clamp_float(pos[1], default=0.0, min_value=-1e6, max_value=1e6)
        else:
            cx, cy = 0.0, 0.0

        label = _as_str(o.get("label") or "")
        color = _as_str(o.get("color") or "#111827")
        fill = _as_str(o.get("fill") or "#ffffff")

        if shape in {"circle", "disk"}:
            r = _clamp_float(o.get("r"), default=1.0, min_value=0.1, max_value=50.0)
            ax.add_patch(Circle((cx, cy), r, edgecolor=color, facecolor=fill, linewidth=2.0, zorder=1.8))
        else:
            size = o.get("size")
            w = 3.0
            h = 2.0
            if isinstance(size, (list, tuple)) and len(size) >= 2:
                w = _clamp_float(size[0], default=3.0, min_value=0.2, max_value=200.0)
                h = _clamp_float(size[1], default=2.0, min_value=0.2, max_value=200.0)
            ax.add_patch(
                Rectangle((cx - w / 2.0, cy - h / 2.0), w, h, edgecolor=color, facecolor=fill, linewidth=2.0, zorder=1.8)
            )

        if oid:
            centers[oid] = (cx, cy)
        if label:
            ax.text(cx, cy, label, ha="center", va="center", fontsize=12, zorder=3.0)
        rendered_any = True

    segments = [s for s in _iter_list(spec.get("segments")) if isinstance(s, (list, tuple)) and len(s) >= 2]
    for s in segments:
        a, b = s[0], s[1]
        plot_path(ax,[(float(a[0]), float(a[1])), (float(b[0]), float(b[1]))], color="#111827", linewidth=2.0)
        rendered_any = True

    wires = [w for w in _iter_list(spec.get("wires")) if isinstance(w, (list, tuple)) and len(w) >= 2]
    for w in wires:
        a, b = w[0], w[1]
        plot_path(ax,[(float(a[0]), float(a[1])), (float(b[0]), float(b[1]))], color="#111827", linewidth=2.0)
        rendered_any = True

    forces = [f for f in _iter_list(spec.get("forces")) if isinstance(f, dict)]
    for f in forces:
        obj = _as_str(f.get("object") or "")
        start = centers.get(obj)
        if not start:
            pos = f.get("pos")
            if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                start = (float(pos[0]), float(pos[1]))
        if not start:
            continue

        direction = f.get("direction")
        dx, dy = 1.0, 0.0
        if isinstance(direction, (list, tuple)) and len(direction) >= 2:
            dx = _clamp_float(direction[0], default=1.0, min_value=-1e6, max_value=1e6)
            dy = _clamp_float(direction[1], default=0.0, min_value=-1e6, max_value=1e6)
        else:
            ang = f.get("angle_deg")
            try:
                a = float(ang)
            except (TypeError, ValueError):
                a = 0.0
            rad = math.radians(a)
            dx, dy = math.cos(rad), math.sin(rad)

        length = _clamp_float(f.get("length"), default=3.2, min_value=0.5, max_value=80.0)
        nx = float(start[0] + dx * length)
        ny = float(start[1] + dy * length)
        color = _as_str(f.get("color") or "#ef4444")
        ax.add_patch(
            FancyArrowPatch(
                start,
                (nx, ny),
                arrowstyle="->",
                mutation_scale=14,
                linewidth=2.2,
                color=color,
                shrinkA=0.0,
                shrinkB=0.0,
                zorder=2.8,
            )
        )

        label = _as_str(f.get("label") or "")
        if label:
            lx, ly = arrow_label_position(start, (nx, ny), distance=max(length * 0.08, 0.25))
            ax.text(lx, ly, label, color=color, fontsize=11, ha="center", va="center", zorder=3.0)
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
            ax.annotate(text, xy=(tx, ty), xytext=(x0, y0), arrowprops={"arrowstyle": "->", "lw": 1.3}, zorder=3.0)
        else:
            ax.text(x0, y0, text, fontsize=11, zorder=3.0)
        rendered_any = True

    elements = [e for e in _iter_list(spec.get("elements")) if isinstance(e, dict)]
    if draw_schematic_elements(
        ax=ax,
        elements=elements,
        x_range=(x_min, x_max),
        y_range=(y_min, y_max),
        patches=(Arc, Circle, FancyArrowPatch, Rectangle),
    ):
        rendered_any = True

    title = _as_str(spec.get("title") or "")
    if title:
        ax.text(0.5, 0.98, title, transform=ax.transAxes, ha="center", va="top", fontsize=14)
        rendered_any = True

    if not rendered_any:
        raise ValueError("no_renderable_elements")

    fmt = spec.get("image_format")
    fmt = fmt.strip().lower() if isinstance(fmt, str) else "png"
    if fmt == "svg":
        return _to_svg_bytes(fig)
    return _to_png_bytes(fig, dpi=dpi)


def render_schematic_with_meta(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Format-aware wrapper around render_schematic."""

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure  # noqa: F401  (warm up backend cache before render_schematic)

    fmt = (
        (spec.get("image_format") or _default_plot_format()).strip().lower()
        if isinstance(spec.get("image_format"), str)
        else _default_plot_format()
    )
    spec_for_render = dict(spec or {})
    spec_for_render["image_format"] = "png" if fmt == "png" else "svg"
    bytes_out = render_schematic(spec_for_render)
    if fmt == "png":
        return {
            "success": True,
            "image_bytes": bytes_out,
            "image_format": "png",
            "image_ext": ".png",
            "image_mime": "image/png",
        }
    return {
        "success": True,
        "image_bytes": bytes_out,
        "image_format": "svg",
        "image_ext": ".svg",
        "image_mime": "image/svg+xml",
    }
