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


class TestTextLintMathSpanExemption(unittest.TestCase):
    """G0 真实缺陷：LaTeX 数学环境参数（\\begin{pmatrix}、\\operatorname{span} 等）
    被占位符正则误判为未填占位符（成稿 300+ 处矩阵全部命中）。数学区间必须先剥离再查占位符。"""

    def test_display_math_environment_args_are_not_placeholders(self) -> None:
        flags = lint_text(
            "矩阵：$$A = \\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}$$，"
            "以及 $$\\begin{bmatrix} 1 \\\\ 2 \\end{bmatrix}$$ 完整。"
        )

        self.assertNotIn("unresolved_placeholder", flags)

    def test_inline_math_operatorname_is_not_placeholder(self) -> None:
        flags = lint_text("记 $\\operatorname{span}\\{v_1, v_2\\}$ 为张成空间。")

        self.assertNotIn("unresolved_placeholder", flags)

    def test_bracket_display_math_environment_args_are_not_placeholders(self) -> None:
        flags = lint_text("公式：\n\\[\\begin{pmatrix} \\lambda_1 & 0 \\\\ 0 & \\lambda_2 \\end{pmatrix}\\]\n完。")

        self.assertNotIn("unresolved_placeholder", flags)

    def test_prose_placeholder_still_flagged(self) -> None:
        flags = lint_text("本节主题为 {topic}，请补充。")

        self.assertIn("unresolved_placeholder", flags)

    def test_placeholder_outside_math_still_flagged_when_math_present(self) -> None:
        flags = lint_text("公式 $\\begin{bmatrix} 1 \\\\ 2 \\end{bmatrix}$ 之外还有 {variable} 残留。")

        self.assertIn("unresolved_placeholder", flags)

    def test_math_exemption_does_not_hide_other_flags(self) -> None:
        # 其他检查仍对原文执行：未闭合行内公式照常命中。
        flags = lint_text("矩阵 $$\\begin{pmatrix} a \\\\ b \\end{pmatrix}$$ 与 $x+1")

        self.assertNotIn("unresolved_placeholder", flags)
        self.assertIn("unbalanced_inline_math", flags)

    def test_paren_inline_math_environment_args_are_not_placeholders(self) -> None:
        # 真实缺陷（实跑 #5）：模型用 \\(...\\) 定界符时，\\begin{bmatrix} 仍被误判占位符。
        flags = lint_text("设 \\(A=\\begin{bmatrix}0&1\\\\1&0\\end{bmatrix}\\)，求特征值。")

        self.assertNotIn("unresolved_placeholder", flags)


if __name__ == "__main__":
    unittest.main()
