from __future__ import annotations

from typing import Any, Dict

from backend.core.plot.parsers import _as_str, _clamp_float


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
