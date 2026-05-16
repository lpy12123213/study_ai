from __future__ import annotations

import math
from typing import Any, List, Tuple

from backend.core.plot.geometry import (
    _axis_point,
    _component_label_layout,
    _component_layout,
    _float_or_none,
    _magnetic_field_points,
    _magnetic_marker_size,
    _polyline_points,
    _xy_pair,
)
from backend.core.plot.parsers import _as_str, _clamp_float, _clamp_int
from backend.core.plot.schematic_primitives import arrow_label_position, draw_magnetic_marker, plot_path
from backend.core.plot.styles import (
    _parse_style,
    _style_color,
    _style_fill,
    _style_fontsize,
    _style_linestyle,
    _style_linewidth,
)


def draw_schematic_elements(
    *,
    ax: Any,
    elements: List[dict[str, Any]],
    x_range: Tuple[float, float],
    y_range: Tuple[float, float],
    patches: Tuple[Any, Any, Any, Any],
) -> bool:
    Arc, Circle, FancyArrowPatch, Rectangle = patches
    x_min, x_max = x_range
    y_min, y_max = y_range
    rendered_any = False
    for element in elements:
        etype = _as_str(element.get("type") or "").lower()
        style = _parse_style(element.get("style"))
        for key in (
            "stroke",
            "color",
            "edgecolor",
            "fill",
            "facecolor",
            "stroke-width",
            "stroke_width",
            "line_width",
            "linewidth",
            "font-size",
            "font_size",
            "fontsize",
            "dashed",
        ):
            if key in element and key not in style:
                style[key] = element.get(key)
        color = _style_color(style, default="#111827")
        fill = _style_fill(style, default="#ffffff")
        default_linewidth = 2.2
        if etype == "rail":
            default_linewidth = 3.0
        elif etype == "conductor":
            default_linewidth = 3.6
        elif etype in {"arrow"}:
            default_linewidth = 2.1
        linewidth = _style_linewidth(style, default=default_linewidth)
        linestyle = _style_linestyle(style)
        text = _as_str(element.get("text") or element.get("content") or element.get("label") or "")

        if etype in {"line", "wire", "rail", "conductor", "path"}:
            points = _polyline_points(element)
            if len(points) >= 2:
                plot_path(ax,points, color=color, linewidth=linewidth, linestyle=linestyle)
                rendered_any = True
        elif etype in {"arrow"}:
            points = _polyline_points(element)
            if len(points) >= 2:
                start = points[0]
                end = points[-1]
                length = math.hypot(float(end[0]) - float(start[0]), float(end[1]) - float(start[1]))
                mutation_scale = _clamp_float(length * 0.12, default=14.0, min_value=10.0, max_value=26.0)
                ax.add_patch(
                    FancyArrowPatch(
                        start,
                        end,
                        arrowstyle="->",
                        mutation_scale=mutation_scale,
                        linewidth=linewidth,
                        color=color,
                        linestyle=linestyle,
                        shrinkA=0.0,
                        shrinkB=0.0,
                        zorder=2.8,
                    )
                )
                if text:
                    lx, ly = arrow_label_position(start, end, distance=max(length * 0.08, 0.25))
                    ax.text(
                        lx,
                        ly,
                        text,
                        fontsize=_style_fontsize(style, default=11.0),
                        color=color,
                        ha="center",
                        va="center",
                        zorder=3.0,
                    )
                rendered_any = True
        elif etype in {"rect", "rectangle", "block"}:
            x = _float_or_none(element.get("x"))
            y = _float_or_none(element.get("y"))
            w = _float_or_none(element.get("width"))
            h = _float_or_none(element.get("height"))
            if None not in {x, y, w, h}:
                ax.add_patch(
                    Rectangle(
                        (float(x), float(y)),
                        float(w),
                        float(h),
                        edgecolor=color,
                        facecolor=fill,
                        linewidth=linewidth,
                        linestyle=linestyle,
                        zorder=1.9,
                    )
                )
                rendered_any = True
        elif etype in {"circle", "disk"}:
            cx = _float_or_none(element.get("cx"))
            cy = _float_or_none(element.get("cy"))
            if cx is None or cy is None:
                center = _xy_pair(element.get("center") or element.get("pos"))
                if center:
                    cx, cy = center
            r = _float_or_none(element.get("r"))
            if None not in {cx, cy, r}:
                ax.add_patch(
                    Circle((float(cx), float(cy)), float(r), edgecolor=color, facecolor=fill, linewidth=linewidth, zorder=1.9)
                )
                rendered_any = True
        elif etype in {"text", "label"}:
            x = _float_or_none(element.get("x"))
            y = _float_or_none(element.get("y"))
            if None not in {x, y} and text:
                dx = _float_or_none(element.get("dx")) or 0.0
                dy = _float_or_none(element.get("dy")) or 0.0
                anchor = _as_str(element.get("anchor") or element.get("align") or style.get("text-anchor") or "").lower()
                ha = {"start": "left", "left": "left", "middle": "center", "center": "center", "end": "right", "right": "right"}.get(
                    anchor,
                    "center",
                )
                va = {"top": "top", "bottom": "bottom", "center": "center", "middle": "center"}.get(anchor, "center")
                ax.text(
                    float(x) + float(dx),
                    float(y) + float(dy),
                    text,
                    fontsize=_style_fontsize(style, default=12.0),
                    color=color,
                    ha=ha,
                    va=va,
                    zorder=3.0,
                )
                rendered_any = True
        elif etype in {"magnetic_field"}:
            points, marker = _magnetic_field_points(element)
            marker_size = _magnetic_marker_size(element, points, (x_min, x_max), (y_min, y_max))
            for px, py in points:
                draw_magnetic_marker(ax,(px, py), marker=marker, size=marker_size, color=color, linewidth=linewidth, circle_cls=Circle)
                rendered_any = True
        elif etype in {"symbol", "inductor", "capacitor", "switch", "sensor", "velocity_sensor"}:
            name = _as_str(element.get("name") or etype).lower()
            center = _xy_pair(element.get("center") or element.get("pos"))
            if center is None:
                x = _float_or_none(element.get("x"))
                y = _float_or_none(element.get("y"))
                if None not in {x, y}:
                    center = (float(x), float(y))
            if center is None:
                continue

            size_value = element.get("size")
            if isinstance(size_value, (list, tuple)) and len(size_value) >= 2:
                sw = _clamp_float(size_value[0], default=30.0, min_value=4.0, max_value=300.0)
                sh = _clamp_float(size_value[1], default=24.0, min_value=4.0, max_value=300.0)
            else:
                default_size = _clamp_float(size_value, default=24.0, min_value=4.0, max_value=300.0)
                sw = default_size
                sh = default_size
            layout = _component_layout(center=center, size=(sw, sh), orientation=element.get("orientation") or "")
            cx, cy = layout["center"]
            main_half = float(layout["main_half"])
            cross_half = float(layout["cross_half"])
            body_half = float(layout["body_half"])

            if "inductor" in name:
                plot_path(ax,[layout["lead_start"], _axis_point(layout, -body_half)], color=color, linewidth=linewidth)
                plot_path(ax,[_axis_point(layout, body_half), layout["lead_end"]], color=color, linewidth=linewidth)
                turns = _clamp_int(element.get("turns"), default=4, min_value=3, max_value=8)
                radius = max(body_half / float(turns), 0.3)
                for idx in range(turns):
                    center_point = _axis_point(layout, -body_half + radius * (2 * idx + 1))
                    ax.add_patch(
                        Arc(
                            center_point,
                            2 * radius,
                            2 * radius,
                            angle=90 if layout["orientation"] == "vertical" else 0,
                            theta1=0,
                            theta2=180,
                            color=color,
                            linewidth=linewidth,
                            zorder=2.3,
                        )
                    )
                if "variable" in name:
                    ax.add_patch(
                        FancyArrowPatch(
                            _axis_point(layout, -body_half * 0.78, -cross_half * 0.78),
                            _axis_point(layout, body_half * 0.78, cross_half * 0.78),
                            arrowstyle="->",
                            mutation_scale=10,
                            linewidth=max(1.0, linewidth - 0.4),
                            color=color,
                            zorder=2.9,
                        )
                    )
                rendered_any = True
            elif "capacitor" in name:
                gap = max(min(main_half * 0.32, body_half * 0.82), 0.35)
                plate_half = max(cross_half * 0.82, 0.35)
                plot_path(ax,[layout["lead_start"], _axis_point(layout, -gap)], color=color, linewidth=linewidth)
                plot_path(ax,[_axis_point(layout, gap), layout["lead_end"]], color=color, linewidth=linewidth)
                if layout["orientation"] == "vertical":
                    plot_path(ax,
                        [_axis_point(layout, -gap, -plate_half), _axis_point(layout, -gap, plate_half)],
                        color=color,
                        linewidth=linewidth,
                    )
                    plot_path(ax,
                        [_axis_point(layout, gap, -plate_half), _axis_point(layout, gap, plate_half)],
                        color=color,
                        linewidth=linewidth,
                    )
                else:
                    plot_path(ax,
                        [_axis_point(layout, -gap, -plate_half), _axis_point(layout, -gap, plate_half)],
                        color=color,
                        linewidth=linewidth,
                    )
                    plot_path(ax,
                        [_axis_point(layout, gap, -plate_half), _axis_point(layout, gap, plate_half)],
                        color=color,
                        linewidth=linewidth,
                    )
                rendered_any = True
            elif "switch" in name:
                gap = max(min(body_half * 0.22, main_half * 0.26), 0.35)
                plot_path(ax,[layout["lead_start"], _axis_point(layout, -gap)], color=color, linewidth=linewidth)
                plot_path(ax,[_axis_point(layout, gap), layout["lead_end"]], color=color, linewidth=linewidth)
                state = _as_str(element.get("state") or "").lower()
                across = 0.0 if state == "closed" else max(cross_half * 0.62, 0.35)
                plot_path(ax,
                    [_axis_point(layout, -gap, 0.0), _axis_point(layout, gap, across)],
                    color=color,
                    linewidth=linewidth,
                )
                rendered_any = True
            elif "sensor" in name:
                radius = max(min(main_half * 0.32, cross_half * 0.88), 0.35)
                plot_path(ax,[layout["lead_start"], _axis_point(layout, -radius)], color=color, linewidth=linewidth)
                plot_path(ax,[_axis_point(layout, radius), layout["lead_end"]], color=color, linewidth=linewidth)
                ax.add_patch(Circle((cx, cy), radius, edgecolor=color, facecolor=fill, linewidth=linewidth, zorder=2.2))
                sensor_text = "v" if "velocity" in name else "S"
                ax.text(
                    cx,
                    cy,
                    sensor_text,
                    fontsize=_style_fontsize(style, default=10.0),
                    color=color,
                    ha="center",
                    va="center",
                    zorder=3.0,
                )
                rendered_any = True
            else:
                radius = max(min(main_half * 0.32, cross_half * 0.88), 0.35)
                ax.add_patch(Circle((cx, cy), radius, edgecolor=color, facecolor=fill, linewidth=linewidth, zorder=2.2))
                rendered_any = True

            if text:
                tx, ty, ha, va = _component_label_layout(
                    center=layout["center"],
                    size=layout["size"],
                    orientation=layout["orientation"],
                    x_range=(x_min, x_max),
                    y_range=(y_min, y_max),
                    label_side=element.get("label_side"),
                    label_offset=element.get("label_offset"),
                )
                ax.text(
                    tx,
                    ty,
                    text,
                    fontsize=_style_fontsize(style, default=11.0),
                    color=color,
                    ha=ha,
                    va=va,
                    zorder=3.0,
                )
                rendered_any = True
    return rendered_any
