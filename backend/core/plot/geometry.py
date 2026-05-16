from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.core.plot.parsers import _as_str, _clamp_float, _clamp_int, _iter_list


def _float_or_none(value: Any) -> Any:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _xy_pair(value: Any) -> Optional[Tuple[float, float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        x = _float_or_none(value[0])
        y = _float_or_none(value[1])
        if x is not None and y is not None:
            return (x, y)
    return None


def _path_points(data: Any) -> List[Tuple[float, float]]:
    raw = _as_str(data)
    if not raw:
        return []
    nums = [float(token) for token in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw)]
    out: List[Tuple[float, float]] = []
    for idx in range(0, len(nums) - 1, 2):
        out.append((nums[idx], nums[idx + 1]))
    return out


def _polyline_points(element: Dict[str, Any]) -> List[Tuple[float, float]]:
    if all(key in element for key in ("x1", "y1", "x2", "y2")):
        x1 = _float_or_none(element.get("x1"))
        y1 = _float_or_none(element.get("y1"))
        x2 = _float_or_none(element.get("x2"))
        y2 = _float_or_none(element.get("y2"))
        if None not in {x1, y1, x2, y2}:
            return [(float(x1), float(y1)), (float(x2), float(y2))]

    for key in ("points", "position"):
        value = element.get(key)
        if isinstance(value, (list, tuple)):
            points = [_xy_pair(item) for item in value]
            out = [point for point in points if point is not None]
            if len(out) >= 2:
                return out

    return _path_points(element.get("data"))


def _element_bounds(element: Dict[str, Any]) -> List[Tuple[float, float]]:
    etype = _as_str(element.get("type") or "").lower()
    points = _polyline_points(element)
    if points:
        return points

    if etype in {"rect", "rectangle", "block"}:
        x = _float_or_none(element.get("x"))
        y = _float_or_none(element.get("y"))
        w = _float_or_none(element.get("width"))
        h = _float_or_none(element.get("height"))
        if None not in {x, y, w, h}:
            return [
                (float(x), float(y)),
                (float(x) + float(w), float(y) + float(h)),
            ]
        center = _xy_pair(element.get("center") or element.get("pos"))
        size = element.get("size")
        if center and isinstance(size, (list, tuple)) and len(size) >= 2:
            sw = _float_or_none(size[0])
            sh = _float_or_none(size[1])
            if None not in {sw, sh}:
                return [
                    (center[0] - float(sw) / 2.0, center[1] - float(sh) / 2.0),
                    (center[0] + float(sw) / 2.0, center[1] + float(sh) / 2.0),
                ]

    if etype in {"circle", "disk"}:
        cx = _float_or_none(element.get("cx"))
        cy = _float_or_none(element.get("cy"))
        if cx is None or cy is None:
            center = _xy_pair(element.get("center") or element.get("pos"))
            if center:
                cx, cy = center
        r = _float_or_none(element.get("r"))
        if None not in {cx, cy, r}:
            return [
                (float(cx) - float(r), float(cy) - float(r)),
                (float(cx) + float(r), float(cy) + float(r)),
            ]

    center = _xy_pair(element.get("center") or element.get("pos"))
    if center:
        return [center]

    x = _float_or_none(element.get("x"))
    y = _float_or_none(element.get("y"))
    if None not in {x, y}:
        return [(float(x), float(y))]
    return []


def _schematic_auto_ranges(spec: Dict[str, Any]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    coords: List[Tuple[float, float]] = []

    objects = [o for o in _iter_list(spec.get("objects")) if isinstance(o, dict)]
    for obj in objects:
        coords.extend(_element_bounds(obj))

    for group_key in ("segments", "wires"):
        for item in _iter_list(spec.get(group_key)):
            if isinstance(item, (list, tuple)):
                for point in item:
                    pair = _xy_pair(point)
                    if pair:
                        coords.append(pair)

    for force in [f for f in _iter_list(spec.get("forces")) if isinstance(f, dict)]:
        start = _xy_pair(force.get("pos"))
        if start:
            coords.append(start)

    for ann in [a for a in _iter_list(spec.get("annotations")) if isinstance(a, dict)]:
        point = _xy_pair([ann.get("x"), ann.get("y")])
        if point:
            coords.append(point)
        arrow_to = _xy_pair(ann.get("arrow_to"))
        if arrow_to:
            coords.append(arrow_to)

    for element in [e for e in _iter_list(spec.get("elements")) if isinstance(e, dict)]:
        coords.extend(_element_bounds(element))

    if not coords:
        return ((-10.0, 10.0), (-6.0, 6.0))

    xs = [point[0] for point in coords]
    ys = [point[1] for point in coords]
    x_min = min(xs)
    x_max = max(xs)
    y_min = min(ys)
    y_max = max(ys)
    x_span = max(1.0, abs(x_max - x_min))
    y_span = max(1.0, abs(y_max - y_min))
    x_pad = max(0.6, x_span * 0.08)
    y_pad = max(0.6, y_span * 0.12)
    return ((x_min - x_pad, x_max + x_pad), (y_min - y_pad, y_max + y_pad))


def _resolve_orientation(raw: Any, sw: float, sh: float) -> str:
    token = _as_str(raw).lower()
    if token in {"vertical", "v", "y", "up", "down"}:
        return "vertical"
    if token in {"horizontal", "h", "x", "left", "right"}:
        return "horizontal"
    if sh > sw * 1.15:
        return "vertical"
    return "horizontal"


def _component_layout(
    *,
    center: Tuple[float, float],
    size: Tuple[float, float],
    orientation: Any = "",
) -> Dict[str, Any]:
    cx, cy = float(center[0]), float(center[1])
    sw = _clamp_float(size[0], default=24.0, min_value=4.0, max_value=300.0)
    sh = _clamp_float(size[1], default=24.0, min_value=4.0, max_value=300.0)
    resolved = _resolve_orientation(orientation, sw, sh)
    main_half = (sh / 2.0) if resolved == "vertical" else (sw / 2.0)
    cross_half = (sw / 2.0) if resolved == "vertical" else (sh / 2.0)
    body_half = max(2.0, min(main_half * 0.58, main_half - max(main_half * 0.12, 1.2)))
    return {
        "center": (cx, cy),
        "size": (sw, sh),
        "orientation": resolved,
        "main_half": main_half,
        "cross_half": cross_half,
        "body_half": body_half,
        "lead_start": (cx, cy - main_half) if resolved == "vertical" else (cx - main_half, cy),
        "lead_end": (cx, cy + main_half) if resolved == "vertical" else (cx + main_half, cy),
    }


def _axis_point(layout: Dict[str, Any], along: float, across: float = 0.0) -> Tuple[float, float]:
    cx, cy = layout["center"]
    if layout["orientation"] == "vertical":
        return (float(cx + across), float(cy + along))
    return (float(cx + along), float(cy + across))


def _component_label_layout(
    *,
    center: Tuple[float, float],
    size: Tuple[float, float],
    orientation: str,
    x_range: Tuple[float, float],
    y_range: Tuple[float, float],
    label_side: Any = "",
    label_offset: Any = None,
) -> Tuple[float, float, str, str]:
    cx, cy = float(center[0]), float(center[1])
    sw = _clamp_float(size[0], default=24.0, min_value=4.0, max_value=300.0)
    sh = _clamp_float(size[1], default=24.0, min_value=4.0, max_value=300.0)
    x_span = max(1.0, abs(float(x_range[1]) - float(x_range[0])))
    y_span = max(1.0, abs(float(y_range[1]) - float(y_range[0])))
    span = max(x_span, y_span)
    side = _as_str(label_side).lower()
    if side not in {"above", "below", "left", "right"}:
        if orientation == "vertical":
            side = "left" if cx >= (float(x_range[0]) + float(x_range[1])) / 2.0 else "right"
        else:
            side = "below" if cy >= (float(y_range[0]) + float(y_range[1])) / 2.0 else "above"

    base_offset = _float_or_none(label_offset)
    if base_offset is None:
        if side in {"above", "below"}:
            base_offset = max(sh * 0.9, span * 0.045)
        else:
            base_offset = max(sw * 0.75, span * 0.04)

    if side == "above":
        return (cx, cy + float(base_offset), "center", "bottom")
    if side == "below":
        return (cx, cy - float(base_offset), "center", "top")
    if side == "left":
        return (cx - float(base_offset), cy, "right", "center")
    return (cx + float(base_offset), cy, "left", "center")


def _magnetic_field_points(element: Dict[str, Any]) -> Tuple[List[Tuple[float, float]], str]:
    raw_symbol = _as_str(element.get("symbol") or element.get("direction") or "").lower()
    if raw_symbol in {"", "x", "cross", "into", "into_page", "in", "down"}:
        marker = "into_page"
    elif raw_symbol in {"dot", "out", "out_of_page", "out-page", "outofpage", "up"}:
        marker = "out_of_page"
    else:
        marker = raw_symbol or "into_page"

    points = _polyline_points(element)
    if points:
        return ([(float(px), float(py)) for px, py in points], marker)

    center = _xy_pair(element.get("center") or element.get("pos"))
    if center is None:
        x = _float_or_none(element.get("x"))
        y = _float_or_none(element.get("y"))
        w = _float_or_none(element.get("width"))
        h = _float_or_none(element.get("height"))
        if None not in {x, y, w, h}:
            cols = _clamp_int(element.get("cols"), default=4, min_value=1, max_value=16)
            rows = _clamp_int(element.get("rows"), default=3, min_value=1, max_value=16)
            pad_x = min(float(w) * 0.15, float(w) / 2.0)
            pad_y = min(float(h) * 0.25, float(h) / 2.0)
            if cols == 1:
                xs = [float(x) + float(w) / 2.0]
            else:
                start_x = float(x) + pad_x
                end_x = float(x) + float(w) - pad_x
                step_x = (end_x - start_x) / float(cols - 1)
                xs = [start_x + step_x * idx for idx in range(cols)]
            if rows == 1:
                ys = [float(y) + float(h) / 2.0]
            else:
                start_y = float(y) + pad_y
                end_y = float(y) + float(h) - pad_y
                step_y = (end_y - start_y) / float(rows - 1)
                ys = [start_y + step_y * idx for idx in range(rows)]
            return (
                [(round(px, 6), round(py, 6)) for py in ys for px in xs],
                marker,
            )

        x1 = _float_or_none(element.get("x1"))
        y1 = _float_or_none(element.get("y1"))
        x2 = _float_or_none(element.get("x2"))
        y2 = _float_or_none(element.get("y2"))
        if None not in {x1, y1, x2, y2}:
            center = ((float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0)

    if center is not None:
        return ([(float(center[0]), float(center[1]))], marker)
    return ([], marker)


def _marker_spacing(points: List[Tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    distances: List[float] = []
    for idx, (x0, y0) in enumerate(points):
        for jdx in range(idx + 1, len(points)):
            x1, y1 = points[jdx]
            dist = math.hypot(x1 - x0, y1 - y0)
            if dist > 1e-6:
                distances.append(dist)
    return min(distances) if distances else 0.0


def _magnetic_marker_size(
    element: Dict[str, Any],
    points: List[Tuple[float, float]],
    x_range: Tuple[float, float],
    y_range: Tuple[float, float],
) -> float:
    explicit = _float_or_none(element.get("size"))
    if explicit is not None and explicit > 0:
        return float(explicit)
    spacing = _marker_spacing(points)
    if spacing > 0:
        return max(spacing * 0.26, 0.18)
    span = max(1.0, abs(float(x_range[1]) - float(x_range[0])), abs(float(y_range[1]) - float(y_range[0])))
    return max(span * 0.03, 0.18)
