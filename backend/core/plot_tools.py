"""Compatibility entrypoint for plotting helpers.

The implementations live under ``backend.core.plot``. This module keeps the
legacy ``backend.core.plot_tools`` import path and selected private helpers that
older tests/callers still reference.
"""

from __future__ import annotations

from backend.core.logging_utils import get_logger
from backend.core.plot.charts import (
    _default_plot_format,
    _to_image_bytes,
    _to_png_bytes,
    _to_svg_bytes,
    render_2d_plot,
    render_2d_plot_with_meta,
    render_3d_plot,
    render_3d_plot_with_meta,
)
from backend.core.plot.expression import _PLOT_EVAL_EXCEPTIONS, _safe_eval_expr
from backend.core.plot.geometry import (
    _axis_point,
    _component_label_layout,
    _component_layout,
    _element_bounds,
    _float_or_none,
    _magnetic_field_points,
    _magnetic_marker_size,
    _marker_spacing,
    _path_points,
    _polyline_points,
    _resolve_orientation,
    _schematic_auto_ranges,
    _xy_pair,
)
from backend.core.plot.parsers import _as_str, _clamp_float, _clamp_int, _iter_list, _parse_range
from backend.core.plot.schematic import render_schematic, render_schematic_with_meta
from backend.core.plot.styles import (
    _parse_style,
    _style_color,
    _style_fill,
    _style_fontsize,
    _style_linestyle,
    _style_linewidth,
    _style_token,
)

logger = get_logger(__name__)

__all__ = [
    "_PLOT_EVAL_EXCEPTIONS",
    "_as_str",
    "_axis_point",
    "_clamp_float",
    "_clamp_int",
    "_component_label_layout",
    "_component_layout",
    "_default_plot_format",
    "_element_bounds",
    "_float_or_none",
    "_iter_list",
    "_magnetic_field_points",
    "_magnetic_marker_size",
    "_marker_spacing",
    "_parse_range",
    "_parse_style",
    "_path_points",
    "_polyline_points",
    "_resolve_orientation",
    "_safe_eval_expr",
    "_schematic_auto_ranges",
    "_style_color",
    "_style_fill",
    "_style_fontsize",
    "_style_linestyle",
    "_style_linewidth",
    "_style_token",
    "_to_image_bytes",
    "_to_png_bytes",
    "_to_svg_bytes",
    "_xy_pair",
    "logger",
    "render_2d_plot",
    "render_2d_plot_with_meta",
    "render_3d_plot",
    "render_3d_plot_with_meta",
    "render_schematic",
    "render_schematic_with_meta",
]
