from __future__ import annotations

import io
import unittest

from PIL import Image

from backend.core.plot.charts import render_2d_plot_with_meta
from backend.core.plot.expression import _safe_eval_expr
from backend.core.plot.geometry import _component_layout, _magnetic_field_points
from backend.core.plot.schematic import render_schematic


class TestPlotTools(unittest.TestCase):
    def _assert_non_blank_png(self, png_bytes: bytes) -> None:
        self.assertIsInstance(png_bytes, bytes)
        self.assertGreater(len(png_bytes), 0)

        with Image.open(io.BytesIO(png_bytes)) as img:
            rgb = img.convert("RGB")
            extrema = rgb.getextrema()
            self.assertTrue(any(channel_min < 250 for channel_min, _channel_max in extrema))

    def test_safe_eval_rejects_unsupported_attribute_access(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_attr"):
            _safe_eval_expr("np.__dict__", variables={"x": 1})

    def test_render_2d_plot_with_meta_reports_invalid_curve_warnings(self) -> None:
        result = render_2d_plot_with_meta(
            {
                "curves": [
                    {"expr": "x**2", "label": "good"},
                    {"expr": "np.__dict__", "label": "bad"},
                ]
            }
        )

        self.assertTrue(result["success"])
        self.assertIsInstance(result["png_bytes"], bytes)
        self.assertGreater(len(result["png_bytes"]), 0)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["warnings"][0]["expr"], "np.__dict__")
        self.assertEqual(result["warnings"][0]["reason"], "unsupported_attr")

    def test_render_2d_plot_with_meta_returns_error_when_nothing_can_be_rendered(self) -> None:
        result = render_2d_plot_with_meta(
            {
                "curves": [
                    {"expr": "np.__dict__", "label": "bad"},
                ]
            }
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "no_renderable_curves")

    def test_render_schematic_supports_element_schema_with_pixel_coordinates(self) -> None:
        png_bytes = render_schematic(
            {
                "width": 800,
                "height": 600,
                "elements": [
                    {"type": "line", "x1": 100, "y1": 300, "x2": 700, "y2": 300},
                    {"type": "line", "x1": 100, "y1": 400, "x2": 700, "y2": 400},
                    {"type": "line", "x1": 160, "y1": 300, "x2": 160, "y2": 400, "line_width": 3},
                    {"type": "text", "x": 250, "y": 250, "text": "B = 0.2 T"},
                    {"type": "arrow", "x1": 160, "y1": 350, "x2": 280, "y2": 350},
                    {"type": "rect", "x": 420, "y": 180, "width": 60, "height": 40},
                    {"type": "circle", "cx": 560, "cy": 200, "r": 24},
                ],
            }
        )

        self._assert_non_blank_png(png_bytes)

    def test_magnetic_field_points_generates_grid_from_region(self) -> None:
        points, marker = _magnetic_field_points(
            {
                "type": "magnetic_field",
                "x": 100,
                "y": 160,
                "width": 180,
                "height": 120,
                "rows": 3,
                "cols": 4,
                "direction": "into_page",
            }
        )

        self.assertEqual(marker, "into_page")
        self.assertEqual(len(points), 12)
        self.assertEqual(points[0], (127.0, 190.0))
        self.assertEqual(points[-1], (253.0, 250.0))

    def test_component_layout_prefers_vertical_terminals_for_tall_symbols(self) -> None:
        layout = _component_layout(center=(300.0, 220.0), size=(36.0, 120.0), orientation="")

        self.assertEqual(layout["orientation"], "vertical")
        self.assertEqual(layout["lead_start"], (300.0, 160.0))
        self.assertEqual(layout["lead_end"], (300.0, 280.0))

    def test_render_schematic_supports_magnetic_field_regions(self) -> None:
        png_bytes = render_schematic(
            {
                "width": 500,
                "height": 360,
                "x_range": [0, 10],
                "y_range": [0, 8],
                "elements": [
                    {"type": "magnetic_field", "x": 2, "y": 2, "width": 6, "height": 4, "rows": 3, "cols": 4},
                ],
            }
        )

        self._assert_non_blank_png(png_bytes)

    def test_render_schematic_raises_when_nothing_can_be_rendered(self) -> None:
        with self.assertRaisesRegex(ValueError, "no_renderable_elements"):
            render_schematic({})
