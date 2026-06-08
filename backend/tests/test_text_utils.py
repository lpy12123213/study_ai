from __future__ import annotations

import unittest

from backend.core.text_lint import lint_text
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

    def test_clip_text_repairs_unclosed_math(self) -> None:
        out = clip_text("这里有 $x^2 + y^2 很长很长", max_chars=12)

        self.assertEqual(out.count("$") % 2, 0)

    def test_clip_text_repairs_unclosed_code_fence(self) -> None:
        out = clip_text("```python\nprint('hello world')", max_chars=18)

        self.assertTrue(out.rstrip().endswith("```"))

    def test_lint_text_detects_common_generation_residue(self) -> None:
        flags = lint_text("令 {variable} = 1，且 $x+1\n```python\nprint(1)")

        self.assertIn("unresolved_placeholder", flags)
        self.assertIn("unbalanced_inline_math", flags)
        self.assertIn("unclosed_code_fence", flags)


if __name__ == "__main__":
    unittest.main()
