from __future__ import annotations

import ast
import io
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)
_PLOT_EVAL_EXCEPTIONS = (ArithmeticError, AttributeError, NameError, SyntaxError, TypeError, ValueError)


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(min_value, min(max_value, n))


def _clamp_float(value: Any, *, default: float, min_value: float, max_value: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = default
    if math.isnan(n) or math.isinf(n):
        n = default
    return max(min_value, min(max_value, n))


def _parse_range(value: Any, *, default: Tuple[float, float], min_span: float = 1e-6) -> Tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        a = _clamp_float(value[0], default=default[0], min_value=-1e9, max_value=1e9)
        b = _clamp_float(value[1], default=default[1], min_value=-1e9, max_value=1e9)
        if a == b:
            b = a + (1.0 if abs(a) < 1e-3 else abs(a) * 0.1 + 1.0)
        if abs(b - a) < min_span:
            b = a + min_span
        return (min(a, b), max(a, b))
    if isinstance(value, dict):
        a = _clamp_float(value.get("min"), default=default[0], min_value=-1e9, max_value=1e9)
        b = _clamp_float(value.get("max"), default=default[1], min_value=-1e9, max_value=1e9)
        if a == b:
            b = a + (1.0 if abs(a) < 1e-3 else abs(a) * 0.1 + 1.0)
        if abs(b - a) < min_span:
            b = a + min_span
        return (min(a, b), max(a, b))
    return default


def _iter_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _parse_style(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        return {"_raw": value.strip()}
    return {}


def _style_token(style: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in style:
            return style.get(key)
    return None


def _style_color(style: Dict[str, Any], *, default: str) -> str:
    value = _style_token(style, "stroke", "color", "edgecolor")
    return _as_str(value or default) or default


def _style_fill(style: Dict[str, Any], *, default: str) -> str:
    value = _style_token(style, "fill", "facecolor")
    fill = _as_str(value or default) or default
    if fill.lower() in {"none", "transparent"}:
        return "none"
    return fill


def _style_linewidth(style: Dict[str, Any], *, default: float) -> float:
    raw = _style_token(style, "stroke-width", "stroke_width", "line_width", "linewidth", "width")
    if isinstance(raw, str):
        raw = raw.replace("px", "").strip()
    return _clamp_float(raw, default=default, min_value=0.2, max_value=20.0)


def _style_fontsize(style: Dict[str, Any], *, default: float) -> float:
    raw = _style_token(style, "font-size", "font_size", "fontsize")
    if isinstance(raw, str):
        raw = raw.replace("px", "").strip()
    return _clamp_float(raw, default=default, min_value=6.0, max_value=72.0)


def _style_linestyle(style: Dict[str, Any]) -> str:
    raw = _as_str(style.get("_raw") or "").lower()
    if bool(_style_token(style, "dashed")) or "dashed" in raw or "dash" in raw:
        return "--"
    return "-"


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


_ALLOWED_FUNCS = {
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "sinh",
    "cosh",
    "tanh",
    "exp",
    "log",
    "ln",
    "log10",
    "sqrt",
    "abs",
    "floor",
    "ceil",
    "sign",
}

_ALLOWED_NAMES = {"x", "y", "pi", "e", "np", *_ALLOWED_FUNCS}

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Attribute,
)


class _ExprValidator(ast.NodeVisitor):
    def visit(self, node: ast.AST):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError("unsupported_expr")
        return super().visit(node)

    def visit_Name(self, node: ast.Name):
        if node.id not in _ALLOWED_NAMES:
            raise ValueError("unsupported_name")
        return None

    def visit_Attribute(self, node: ast.Attribute):
        if not isinstance(node.value, ast.Name) or node.value.id != "np":
            raise ValueError("unsupported_attr")
        if node.attr not in _ALLOWED_FUNCS and node.attr not in {"pi", "e"}:
            raise ValueError("unsupported_attr")
        return None

    def visit_Call(self, node: ast.Call):
        fn = node.func
        if isinstance(fn, ast.Name):
            if fn.id not in _ALLOWED_FUNCS:
                raise ValueError("unsupported_call")
        elif isinstance(fn, ast.Attribute):
            self.visit_Attribute(fn)
        else:
            raise ValueError("unsupported_call")

        if node.keywords:
            raise ValueError("unsupported_call")

        for a in node.args:
            self.visit(a)
        return None


def _safe_eval_expr(expr: str, *, variables: Dict[str, Any]) -> Any:
    raw = _as_str(expr)
    if not raw:
        raise ValueError("empty_expr")
    raw = raw.replace("^", "**")
    tree = ast.parse(raw, mode="eval")
    _ExprValidator().visit(tree)

    import numpy as np

    env: Dict[str, Any] = {
        "np": np,
        "pi": float(np.pi),
        "e": float(np.e),
        "sin": np.sin,
        "cos": np.cos,
        "tan": np.tan,
        "asin": np.arcsin,
        "acos": np.arccos,
        "atan": np.arctan,
        "sinh": np.sinh,
        "cosh": np.cosh,
        "tanh": np.tanh,
        "exp": np.exp,
        "log": np.log,
        "ln": np.log,
        "log10": np.log10,
        "sqrt": np.sqrt,
        "abs": np.abs,
        "floor": np.floor,
        "ceil": np.ceil,
        "sign": np.sign,
    }
    env.update(variables)
    return eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, env)


def _to_png_bytes(fig: Any, *, dpi: int) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    return buf.getvalue()


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

    if any(_as_str(c.get("label") or "") for c in curves):
        ax.legend(loc="best")

    if not rendered_any:
        return {"success": False, "error": "no_renderable_curves", "warnings": warnings, "png_bytes": b""}

    return {"success": True, "png_bytes": _to_png_bytes(fig, dpi=dpi), "warnings": warnings}


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
    except Exception as exc:
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

    def _plot_path(
        points: List[Tuple[float, float]],
        *,
        color: str,
        linewidth: float,
        linestyle: str = "-",
        zorder: float = 2.0,
    ) -> None:
        ax.plot(
            [point[0] for point in points],
            [point[1] for point in points],
            color=color,
            linewidth=linewidth,
            linestyle=linestyle,
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=zorder,
        )

    def _arrow_label_position(
        start: Tuple[float, float],
        end: Tuple[float, float],
        *,
        distance: float,
    ) -> Tuple[float, float]:
        mx = (float(start[0]) + float(end[0])) / 2.0
        my = (float(start[1]) + float(end[1])) / 2.0
        dx = float(end[0]) - float(start[0])
        dy = float(end[1]) - float(start[1])
        norm = math.hypot(dx, dy) or 1.0
        return (mx - dy / norm * distance, my + dx / norm * distance)

    def _draw_magnetic_marker(
        center: Tuple[float, float],
        *,
        marker: str,
        size: float,
        color: str,
        linewidth: float,
    ) -> None:
        px, py = float(center[0]), float(center[1])
        radius = max(float(size) * 0.45, 0.06)
        if marker == "out_of_page":
            ax.add_patch(
                Circle((px, py), radius, edgecolor=color, facecolor="none", linewidth=max(0.8, linewidth * 0.8), zorder=2.5)
            )
            ax.add_patch(Circle((px, py), max(radius * 0.24, 0.03), edgecolor="none", facecolor=color, zorder=2.6))
            return
        if marker == "into_page":
            ax.add_patch(
                Circle((px, py), radius, edgecolor=color, facecolor="none", linewidth=max(0.8, linewidth * 0.8), zorder=2.5)
            )
            arm = radius * 0.58
            _plot_path(
                [(px - arm, py - arm), (px + arm, py + arm)],
                color=color,
                linewidth=max(0.8, linewidth * 0.85),
                zorder=2.6,
            )
            _plot_path(
                [(px - arm, py + arm), (px + arm, py - arm)],
                color=color,
                linewidth=max(0.8, linewidth * 0.85),
                zorder=2.6,
            )
            return
        ax.text(px, py, marker or "×", fontsize=max(size * 1.8, 10.0), color=color, ha="center", va="center", zorder=2.6)

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
        _plot_path([(float(a[0]), float(a[1])), (float(b[0]), float(b[1]))], color="#111827", linewidth=2.0)
        rendered_any = True

    wires = [w for w in _iter_list(spec.get("wires")) if isinstance(w, (list, tuple)) and len(w) >= 2]
    for w in wires:
        a, b = w[0], w[1]
        _plot_path([(float(a[0]), float(a[1])), (float(b[0]), float(b[1]))], color="#111827", linewidth=2.0)
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
            lx, ly = _arrow_label_position(start, (nx, ny), distance=max(length * 0.08, 0.25))
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
                _plot_path(points, color=color, linewidth=linewidth, linestyle=linestyle)
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
                    lx, ly = _arrow_label_position(start, end, distance=max(length * 0.08, 0.25))
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
                _draw_magnetic_marker((px, py), marker=marker, size=marker_size, color=color, linewidth=linewidth)
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
                _plot_path([layout["lead_start"], _axis_point(layout, -body_half)], color=color, linewidth=linewidth)
                _plot_path([_axis_point(layout, body_half), layout["lead_end"]], color=color, linewidth=linewidth)
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
                _plot_path([layout["lead_start"], _axis_point(layout, -gap)], color=color, linewidth=linewidth)
                _plot_path([_axis_point(layout, gap), layout["lead_end"]], color=color, linewidth=linewidth)
                if layout["orientation"] == "vertical":
                    _plot_path(
                        [_axis_point(layout, -gap, -plate_half), _axis_point(layout, -gap, plate_half)],
                        color=color,
                        linewidth=linewidth,
                    )
                    _plot_path(
                        [_axis_point(layout, gap, -plate_half), _axis_point(layout, gap, plate_half)],
                        color=color,
                        linewidth=linewidth,
                    )
                else:
                    _plot_path(
                        [_axis_point(layout, -gap, -plate_half), _axis_point(layout, -gap, plate_half)],
                        color=color,
                        linewidth=linewidth,
                    )
                    _plot_path(
                        [_axis_point(layout, gap, -plate_half), _axis_point(layout, gap, plate_half)],
                        color=color,
                        linewidth=linewidth,
                    )
                rendered_any = True
            elif "switch" in name:
                gap = max(min(body_half * 0.22, main_half * 0.26), 0.35)
                _plot_path([layout["lead_start"], _axis_point(layout, -gap)], color=color, linewidth=linewidth)
                _plot_path([_axis_point(layout, gap), layout["lead_end"]], color=color, linewidth=linewidth)
                state = _as_str(element.get("state") or "").lower()
                across = 0.0 if state == "closed" else max(cross_half * 0.62, 0.35)
                _plot_path(
                    [_axis_point(layout, -gap, 0.0), _axis_point(layout, gap, across)],
                    color=color,
                    linewidth=linewidth,
                )
                rendered_any = True
            elif "sensor" in name:
                radius = max(min(main_half * 0.32, cross_half * 0.88), 0.35)
                _plot_path([layout["lead_start"], _axis_point(layout, -radius)], color=color, linewidth=linewidth)
                _plot_path([_axis_point(layout, radius), layout["lead_end"]], color=color, linewidth=linewidth)
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

    title = _as_str(spec.get("title") or "")
    if title:
        ax.text(0.5, 0.98, title, transform=ax.transAxes, ha="center", va="top", fontsize=14)
        rendered_any = True

    if not rendered_any:
        raise ValueError("no_renderable_elements")

    return _to_png_bytes(fig, dpi=dpi)
