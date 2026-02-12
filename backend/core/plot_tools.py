from __future__ import annotations

import ast
import io
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(min_value, min(max_value, n))


def _clamp_float(value: Any, *, default: float, min_value: float, max_value: float) -> float:
    try:
        n = float(value)
    except Exception:
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


def render_2d_plot(spec: Dict[str, Any]) -> bytes:
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
        except Exception:
            continue
        if y.shape != x.shape:
            continue
        mask = np.isfinite(y)
        if not mask.any():
            continue
        ax.plot(x[mask], y[mask], style, color=(color or None), linewidth=lw, label=(label or None))

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
            except Exception:
                continue
            try:
                ax.contour(X, Y, Z, levels=[0.0], colors=[color], linewidths=[lw])
            except Exception:
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
        except Exception:
            continue
        ax.axvline(xv, color="#9ca3af", linewidth=1.3, linestyle="--", alpha=0.9)

    hlines = [v for v in _iter_list(spec.get("hlines")) if isinstance(v, (int, float, str, dict))]
    for v in hlines:
        y0 = None
        if isinstance(v, dict):
            y0 = v.get("y")
        else:
            y0 = v
        try:
            yv = float(y0)
        except Exception:
            continue
        ax.axhline(yv, color="#9ca3af", linewidth=1.3, linestyle="--", alpha=0.9)

    tangent_lines = [t for t in _iter_list(spec.get("tangent_lines")) if isinstance(t, dict)]
    for t in tangent_lines:
        idx = t.get("curve_index")
        try:
            ci = int(idx)
        except Exception:
            continue
        if ci < 0 or ci >= len(curves):
            continue
        c = curves[ci]
        expr = _as_str(c.get("expr"))
        if not expr:
            continue
        try:
            x0 = float(t.get("at_x"))
        except Exception:
            continue

        h = _clamp_float(t.get("h"), default=1e-3, min_value=1e-6, max_value=1.0)
        try:
            y0 = float(_safe_eval_expr(expr, variables={"x": x0}))
            yp = float(_safe_eval_expr(expr, variables={"x": x0 + h}))
            ym = float(_safe_eval_expr(expr, variables={"x": x0 - h}))
        except Exception:
            continue
        m = (yp - ym) / (2.0 * h)
        xs = np.array([float(x_min), float(x_max)], dtype=float)
        ys = y0 + m * (xs - x0)
        color = _as_str(t.get("color") or "#ef4444")
        lw = _clamp_float(t.get("linewidth"), default=2.2, min_value=0.6, max_value=6.0)
        ax.plot(xs, ys, "-", color=color, linewidth=lw)
        ax.scatter([x0], [y0], s=20, color=color)

    points = [p for p in _iter_list(spec.get("points")) if isinstance(p, dict)]
    for p in points:
        try:
            px = float(p.get("x"))
            py = float(p.get("y"))
        except Exception:
            continue
        label = _as_str(p.get("label") or "")
        ax.scatter([px], [py], s=32, color=_as_str(p.get("color") or "#111827"))
        if label:
            ax.text(px, py, f" {label}", fontsize=10)

    annotations = [a for a in _iter_list(spec.get("annotations")) if isinstance(a, dict)]
    for a in annotations:
        text = _as_str(a.get("text") or "")
        if not text:
            continue
        try:
            x0 = float(a.get("x"))
            y0 = float(a.get("y"))
        except Exception:
            continue
        arrow_to = a.get("arrow_to")
        if isinstance(arrow_to, (list, tuple)) and len(arrow_to) >= 2:
            try:
                tx = float(arrow_to[0])
                ty = float(arrow_to[1])
            except Exception:
                tx, ty = x0, y0
            ax.annotate(text, xy=(tx, ty), xytext=(x0, y0), arrowprops={"arrowstyle": "->", "lw": 1.3})
        else:
            ax.text(x0, y0, text, fontsize=10)

    ax.set_xlim(float(x_min), float(x_max))
    if y_range is not None:
        y_min, y_max = _parse_range(y_range, default=(-5.0, 5.0))
        ax.set_ylim(float(y_min), float(y_max))

    if aspect_equal:
        ax.set_aspect("equal", adjustable="box")

    if any(_as_str(c.get("label") or "") for c in curves):
        ax.legend(loc="best")

    return _to_png_bytes(fig, dpi=dpi)


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
    except Exception:
        pass

    return _to_png_bytes(fig, dpi=dpi)


def render_schematic(spec: Dict[str, Any]) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
    from matplotlib.figure import Figure
    from matplotlib.patches import Circle, FancyArrowPatch, Rectangle

    width = _clamp_int(spec.get("width"), default=900, min_value=420, max_value=2000)
    height = _clamp_int(spec.get("height"), default=520, min_value=320, max_value=1400)
    dpi = _clamp_int(spec.get("dpi"), default=150, min_value=72, max_value=240)

    fig = Figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    FigureCanvas(fig)
    ax = fig.add_subplot(111)

    x_min, x_max = _parse_range(spec.get("x_range"), default=(-10.0, 10.0))
    y_min, y_max = _parse_range(spec.get("y_range"), default=(-6.0, 6.0))
    ax.set_xlim(float(x_min), float(x_max))
    ax.set_ylim(float(y_min), float(y_max))
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    objects = [o for o in _iter_list(spec.get("objects")) if isinstance(o, dict)]
    centers: Dict[str, Tuple[float, float]] = {}
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
            ax.add_patch(Circle((cx, cy), r, edgecolor=color, facecolor=fill, linewidth=2.0))
        else:
            size = o.get("size")
            w = 3.0
            h = 2.0
            if isinstance(size, (list, tuple)) and len(size) >= 2:
                w = _clamp_float(size[0], default=3.0, min_value=0.2, max_value=200.0)
                h = _clamp_float(size[1], default=2.0, min_value=0.2, max_value=200.0)
            ax.add_patch(Rectangle((cx - w / 2.0, cy - h / 2.0), w, h, edgecolor=color, facecolor=fill, linewidth=2.0))

        if oid:
            centers[oid] = (cx, cy)
        if label:
            ax.text(cx, cy, label, ha="center", va="center", fontsize=12)

    segments = [s for s in _iter_list(spec.get("segments")) if isinstance(s, (list, tuple)) and len(s) >= 2]
    for s in segments:
        a, b = s[0], s[1]
        ax.plot([float(a[0]), float(b[0])], [float(a[1]), float(b[1])], color="#111827", linewidth=2.0)

    wires = [w for w in _iter_list(spec.get("wires")) if isinstance(w, (list, tuple)) and len(w) >= 2]
    for w in wires:
        a, b = w[0], w[1]
        ax.plot([float(a[0]), float(b[0])], [float(a[1]), float(b[1])], color="#111827", linewidth=2.0)

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
            except Exception:
                a = 0.0
            rad = math.radians(a)
            dx, dy = math.cos(rad), math.sin(rad)

        length = _clamp_float(f.get("length"), default=3.2, min_value=0.5, max_value=80.0)
        nx = float(start[0] + dx * length)
        ny = float(start[1] + dy * length)
        color = _as_str(f.get("color") or "#ef4444")
        ax.add_patch(FancyArrowPatch(start, (nx, ny), arrowstyle="->", mutation_scale=14, linewidth=2.2, color=color))

        label = _as_str(f.get("label") or "")
        if label:
            ax.text((start[0] + nx) / 2.0, (start[1] + ny) / 2.0, label, color=color, fontsize=11)

    annotations = [a for a in _iter_list(spec.get("annotations")) if isinstance(a, dict)]
    for a in annotations:
        text = _as_str(a.get("text") or "")
        if not text:
            continue
        try:
            x0 = float(a.get("x"))
            y0 = float(a.get("y"))
        except Exception:
            continue
        arrow_to = a.get("arrow_to")
        if isinstance(arrow_to, (list, tuple)) and len(arrow_to) >= 2:
            try:
                tx = float(arrow_to[0])
                ty = float(arrow_to[1])
            except Exception:
                tx, ty = x0, y0
            ax.annotate(text, xy=(tx, ty), xytext=(x0, y0), arrowprops={"arrowstyle": "->", "lw": 1.3})
        else:
            ax.text(x0, y0, text, fontsize=11)

    title = _as_str(spec.get("title") or "")
    if title:
        ax.text(0.5, 0.98, title, transform=ax.transAxes, ha="center", va="top", fontsize=14)

    return _to_png_bytes(fig, dpi=dpi)
