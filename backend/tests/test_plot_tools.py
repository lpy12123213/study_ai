from __future__ import annotations

import unittest

from backend.core import plot_tools


class TestPlotTools(unittest.TestCase):
    def test_safe_eval_rejects_unsupported_attribute_access(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_attr"):
            plot_tools._safe_eval_expr("np.__dict__", variables={"x": 1})

    def test_render_2d_plot_with_meta_reports_invalid_curve_warnings(self) -> None:
        result = plot_tools.render_2d_plot_with_meta(
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
        result = plot_tools.render_2d_plot_with_meta(
            {
                "curves": [
                    {"expr": "np.__dict__", "label": "bad"},
                ]
            }
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "no_renderable_curves")
