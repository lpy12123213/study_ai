from __future__ import annotations

import html
import math
from typing import Any, Dict, List, Optional, Tuple

from backend.shared.numparse import clamp_float as _clamp_float
from backend.shared.numparse import clamp_int as _clamp_int


def _as_str(value: Any) -> str:
    return str(value or "").strip()





def _safe_text(value: Any) -> str:
    return html.escape(_as_str(value), quote=True)


def _iter_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _parse_point(value: Any) -> Optional[Tuple[float, float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return (float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            return None
    if isinstance(value, dict):
        try:
            return (float(value.get("x")), float(value.get("y")))
        except (TypeError, ValueError):
            return None
    return None


def _line_rect_intersections(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    *,
    width: float,
    height: float,
) -> List[Tuple[float, float, float]]:
    """Return intersections as (t, x, y) for the infinite line p(t)=p1+t*(p2-p1)."""

    x1, y1 = p1
    x2, y2 = p2
    dx = x2 - x1
    dy = y2 - y1

    out: List[Tuple[float, float, float]] = []

    def _add(t: float, x: float, y: float) -> None:
        # Keep only intersections within the rectangle bounds (with a small tolerance).
        eps = 1e-6
        if -eps <= x <= width + eps and -eps <= y <= height + eps:
            out.append((t, float(x), float(y)))

    if abs(dx) > 1e-9:
        # x = 0
        t = (0.0 - x1) / dx
        _add(t, 0.0, y1 + t * dy)
        # x = width
        t = (width - x1) / dx
        _add(t, width, y1 + t * dy)

    if abs(dy) > 1e-9:
        # y = 0
        t = (0.0 - y1) / dy
        _add(t, x1 + t * dx, 0.0)
        # y = height
        t = (height - y1) / dy
        _add(t, x1 + t * dx, height)

    # De-dup near-identical points.
    deduped: List[Tuple[float, float, float]] = []
    for t, x, y in out:
        if any(abs(x - x2) < 1e-6 and abs(y - y2) < 1e-6 for _, x2, y2 in deduped):
            continue
        deduped.append((t, x, y))
    deduped.sort(key=lambda it: it[0])
    return deduped


def _extend_line_to_rect(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    *,
    width: float,
    height: float,
) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    inter = _line_rect_intersections(p1, p2, width=width, height=height)
    if len(inter) < 2:
        return None
    _, x_a, y_a = inter[0]
    _, x_b, y_b = inter[-1]
    return ((x_a, y_a), (x_b, y_b))


def render_svg_diagram(spec: Dict[str, Any]) -> str:
    """根据图表规格渲染安全的SVG字符串。

    支持的规格键（均为可选）：
    - width, height, padding：宽度、高度、内边距
    - style: stroke, strokeWidth, pointRadius, fontSize, pointFill, pointStroke（样式设置）
    - background: 背景颜色字符串
    - points: { "A": [x,y], "B": {"x":..,"y":..} }（点坐标）
    - segments: [ ["A","B"], {"from":"A","to":"B","extend":true,"dash":"5,5"} ]（线段）
    - polygons: [ ["A","B","C"] ]（多边形）
    - circles: [ {"center":"O","r":80}, {"center":"O","through":"A"} ]（圆）
    - labels: [ {"point":"A","text":"A","dx":-10,"dy":-10} ]（标签）
    - texts: [ {"x":..,"y":..,"text":"...","fontSize":14} ]（文本）
    - caption: str（标题/说明）
    """

    width = _clamp_int(spec.get("width"), default=560, min_value=200, max_value=1400)
    height = _clamp_int(spec.get("height"), default=320, min_value=200, max_value=1000)
    padding = _clamp_int(spec.get("padding"), default=24, min_value=0, max_value=200)

    style = spec.get("style") if isinstance(spec.get("style"), dict) else {}
    stroke = _as_str(style.get("stroke") or "#111827")
    stroke_width = _clamp_float(style.get("strokeWidth"), default=2.0, min_value=0.5, max_value=8.0)
    point_radius = _clamp_float(style.get("pointRadius"), default=4.0, min_value=1.0, max_value=12.0)
    point_fill = _as_str(style.get("pointFill") or "#ffffff")
    point_stroke = _as_str(style.get("pointStroke") or stroke)
    font_size = _clamp_float(style.get("fontSize"), default=14.0, min_value=8.0, max_value=28.0)
    font_family = _as_str(
        style.get("fontFamily")
        or "system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,'Noto Sans','Apple Color Emoji','Segoe UI Emoji'"
    )

    background = _as_str(spec.get("background") or "")

    # Points
    raw_points = spec.get("points") if isinstance(spec.get("points"), dict) else {}
    points: Dict[str, Tuple[float, float]] = {}
    for name, value in raw_points.items():
        key = _as_str(name)
        if not key:
            continue
        p = _parse_point(value)
        if not p:
            continue
        x = _clamp_float(p[0], default=0.0, min_value=float(-width), max_value=float(width * 2))
        y = _clamp_float(p[1], default=0.0, min_value=float(-height), max_value=float(height * 2))
        points[key] = (x, y)

    # Assemble SVG elements.
    elems: List[str] = []

    # Background
    if background:
        elems.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="{_safe_text(background)}" />')

    # Clip region (so extended lines don't overflow)
    elems.append(
        f'<defs><clipPath id="clip"><rect x="{padding}" y="{padding}" width="{width - 2 * padding}" height="{height - 2 * padding}" /></clipPath></defs>'
    )

    # Main drawing group
    elems.append('<g clip-path="url(#clip)">')

    def _get_point(name: str) -> Optional[Tuple[float, float]]:
        return points.get(name)

    # Polygons
    for poly in _iter_list(spec.get("polygons")):
        names = [str(x or "").strip() for x in _iter_list(poly)]
        coords: List[str] = []
        for n in names:
            p = _get_point(n)
            if not p:
                continue
            coords.append(f"{p[0]},{p[1]}")
        if len(coords) >= 3:
            pts = " ".join(coords)
            elems.append(
                f'<polygon points="{pts}" fill="none" stroke="{_safe_text(stroke)}" stroke-width="{stroke_width}" />'
            )

    # Segments / Lines
    for seg in _iter_list(spec.get("segments")):
        a = ""
        b = ""
        extend = False
        dash = ""
        arrow = False
        seg_stroke = stroke
        seg_width = stroke_width

        if isinstance(seg, (list, tuple)) and len(seg) >= 2:
            a = _as_str(seg[0])
            b = _as_str(seg[1])
        elif isinstance(seg, dict):
            a = _as_str(seg.get("from"))
            b = _as_str(seg.get("to"))
            extend = bool(seg.get("extend", False))
            dash = _as_str(seg.get("dash") or "")
            arrow = bool(seg.get("arrow", False))
            seg_stroke = _as_str(seg.get("stroke") or stroke)
            seg_width = _clamp_float(seg.get("strokeWidth"), default=stroke_width, min_value=0.5, max_value=8.0)
        else:
            continue

        p1 = _get_point(a)
        p2 = _get_point(b)
        if not p1 or not p2:
            continue

        if extend:
            extended = _extend_line_to_rect(p1, p2, width=float(width), height=float(height))
            if not extended:
                continue
            (x1, y1), (x2, y2) = extended
        else:
            x1, y1 = p1
            x2, y2 = p2

        dash_attr = f' stroke-dasharray="{_safe_text(dash)}"' if dash else ""
        # Arrow markers are optional and kept simple.
        marker_end = ' marker-end="url(#arrow)"' if arrow else ""
        elems.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{_safe_text(seg_stroke)}" stroke-width="{seg_width}"{dash_attr}{marker_end} />'
        )

    # Circles
    for circ in _iter_list(spec.get("circles")):
        if not isinstance(circ, dict):
            continue
        center_name = _as_str(circ.get("center"))
        center = _get_point(center_name) if center_name else None
        if not center:
            center = _parse_point(circ.get("center"))
        if not center:
            continue

        r = circ.get("r")
        through = _as_str(circ.get("through"))
        radius: Optional[float] = None
        if r is not None:
            try:
                radius = float(r)
            except (TypeError, ValueError):
                radius = None
        elif through:
            tp = _get_point(through)
            if tp:
                radius = math.hypot(tp[0] - center[0], tp[1] - center[1])
        if radius is None or radius <= 0:
            continue

        elems.append(
            f'<circle cx="{center[0]}" cy="{center[1]}" r="{radius}" fill="none" stroke="{_safe_text(stroke)}" stroke-width="{stroke_width}" />'
        )

    elems.append("</g>")

    # Points and labels are drawn after lines so they appear on top.
    for name, (x, y) in points.items():
        elems.append(
            f'<circle cx="{x}" cy="{y}" r="{point_radius}" fill="{_safe_text(point_fill)}" stroke="{_safe_text(point_stroke)}" stroke-width="1.5" />'
        )

    # Labels
    for lab in _iter_list(spec.get("labels")):
        if not isinstance(lab, dict):
            continue
        p_name = _as_str(lab.get("point"))
        p = _get_point(p_name)
        if not p:
            continue
        text = _safe_text(lab.get("text") or p_name)
        dx = _clamp_float(lab.get("dx"), default=8.0, min_value=-200.0, max_value=200.0)
        dy = _clamp_float(lab.get("dy"), default=-8.0, min_value=-200.0, max_value=200.0)
        size = _clamp_float(lab.get("fontSize"), default=font_size, min_value=8.0, max_value=28.0)
        elems.append(
            f'<text x="{p[0] + dx}" y="{p[1] + dy}" font-size="{size}" font-family="{_safe_text(font_family)}" fill="#111827">{text}</text>'
        )

    # Free texts
    for t in _iter_list(spec.get("texts")):
        if not isinstance(t, dict):
            continue
        p = _parse_point(t)
        if not p:
            # allow {x,y}
            p = _parse_point({"x": t.get("x"), "y": t.get("y")})
        if not p:
            continue
        text = _safe_text(t.get("text"))
        size = _clamp_float(t.get("fontSize"), default=font_size, min_value=8.0, max_value=28.0)
        anchor = _as_str(t.get("anchor") or "")
        anchor_attr = f' text-anchor="{_safe_text(anchor)}"' if anchor in {"start", "middle", "end"} else ""
        elems.append(
            f'<text x="{p[0]}" y="{p[1]}" font-size="{size}" font-family="{_safe_text(font_family)}" fill="#111827"{anchor_attr}>{text}</text>'
        )

    caption = _as_str(spec.get("caption") or "")
    if caption:
        elems.append(
            f'<text x="{padding}" y="{height - max(8, padding // 2)}" font-size="{max(10.0, font_size - 2)}" font-family="{_safe_text(font_family)}" fill="#6b7280">{_safe_text(caption)}</text>'
        )

    # Optional arrow marker (defined even if unused to keep rendering stable).
    defs = (
        "<defs>"
        '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{_safe_text(stroke)}" />'
        "</marker>"
        "</defs>"
    )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        + defs
        + "".join(elems)
        + "</svg>"
    )
    return svg
