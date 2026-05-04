from __future__ import annotations

import unittest

from backend.core.text_utils import clip_text


class TestTextUtils(unittest.TestCase):
    def test_clip_text_strips_and_preserves_short_text(self) -> None:
        self.assertEqual(clip_text("  hello  ", max_chars=10), "hello")

    def test_clip_text_uses_ellipsis_within_limit(self) -> None:
        self.assertEqual(clip_text("abcdef", max_chars=4), "abc…")

    def test_clip_text_handles_empty_limit(self) -> None:
        self.assertEqual(clip_text("abcdef", max_chars=0), "")

    def test_clip_text_supports_custom_ellipsis(self) -> None:
        self.assertEqual(clip_text("abcdef", max_chars=4, ellipsis=".."), "ab..")


if __name__ == "__main__":
    unittest.main()
