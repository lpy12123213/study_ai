"""Unit tests for backend.shared.numparse clamp helpers."""

from __future__ import annotations

import unittest

from backend.shared.numparse import clamp_float, clamp_float_optional, clamp_int, clamp_int_optional


class TestClampInt(unittest.TestCase):
    def test_parses_and_clamps(self) -> None:
        self.assertEqual(clamp_int("5", default=1, min_value=1, max_value=10), 5)
        self.assertEqual(clamp_int(99, default=1, min_value=1, max_value=10), 10)
        self.assertEqual(clamp_int(-3, default=1, min_value=1, max_value=10), 1)

    def test_fallback_default(self) -> None:
        self.assertEqual(clamp_int(None, default=4, min_value=1, max_value=10), 4)
        self.assertEqual(clamp_int("abc", default=4, min_value=1, max_value=10), 4)
        self.assertEqual(clamp_int("7.9", default=4, min_value=1, max_value=10), 4)

    def test_default_is_clamped(self) -> None:
        self.assertEqual(clamp_int(None, default=99, min_value=1, max_value=10), 10)


class TestClampFloat(unittest.TestCase):
    def test_parses_and_clamps(self) -> None:
        self.assertEqual(clamp_float("0.5", default=0.1, min_value=0.0, max_value=1.0), 0.5)
        self.assertEqual(clamp_float(2.5, default=0.1, min_value=0.0, max_value=1.0), 1.0)

    def test_nan_and_inf_fall_back_to_default(self) -> None:
        self.assertEqual(clamp_float(float("nan"), default=0.3, min_value=0.0, max_value=1.0), 0.3)
        self.assertEqual(clamp_float(float("inf"), default=0.3, min_value=0.0, max_value=1.0), 0.3)
        self.assertEqual(clamp_float("nan", default=0.3, min_value=0.0, max_value=1.0), 0.3)


class TestClampIntOptional(unittest.TestCase):
    def test_none_default_passthrough(self) -> None:
        self.assertIsNone(clamp_int_optional(None, default=None, min_value=1, max_value=10))
        self.assertIsNone(clamp_int_optional("abc", default=None, min_value=1, max_value=10))

    def test_clamps_parsed_and_default(self) -> None:
        self.assertEqual(clamp_int_optional("20", default=1, min_value=1, max_value=10), 10)
        self.assertEqual(clamp_int_optional(None, default=99, min_value=1, max_value=10), 10)


class TestClampFloatOptional(unittest.TestCase):
    def test_none_default_passthrough(self) -> None:
        self.assertIsNone(clamp_float_optional(None, default=None, min_value=0.0, max_value=1.0))
        self.assertIsNone(clamp_float_optional("abc", default=None, min_value=0.0, max_value=1.0))

    def test_clamps_parsed(self) -> None:
        self.assertEqual(clamp_float_optional("0.7", default=None, min_value=0.0, max_value=1.0), 0.7)
        self.assertEqual(clamp_float_optional(9.9, default=None, min_value=0.0, max_value=1.0), 1.0)

    def test_nan_falls_back_to_default(self) -> None:
        self.assertEqual(clamp_float_optional("nan", default=0.2, min_value=0.0, max_value=1.0), 0.2)
        self.assertIsNone(clamp_float_optional("nan", default=None, min_value=0.0, max_value=1.0))


if __name__ == "__main__":
    unittest.main()
