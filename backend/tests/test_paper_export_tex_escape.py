import unittest


class TestPaperExportTexEscape(unittest.TestCase):
    def test_tex_escape_does_not_double_escape_replacement(self) -> None:
        from backend.paper_compose.export import render_paper_latex

        paper = {
            "paper_name": r"试卷\\名称",
            "questions": [
                {
                    "order": 1,
                    "question_id": r"ai_1\\2",
                    "type": "解答题",
                    "difficulty": "中等",
                    "knowledge_point": r"集合\\函数",
                    "source_url": r"https://example.com/a?b=c\\d",
                    "stem": r"包含反斜线 \\ 的题干 { }",
                }
            ],
        }
        tex = render_paper_latex(paper, include_stem=True, include_answer=False, include_analysis=False)

        # Core expectation: backslashes are escaped as \textbackslash{} and
        # the braces inside that replacement must NOT be escaped again.
        self.assertIn(r"\textbackslash{}", tex)
        self.assertNotIn(r"\textbackslash\{\}", tex)

    def test_tex_escape_preserves_math_spans(self) -> None:
        from backend.paper_compose.export import render_paper_latex

        paper = {
            "paper_name": "math",
            "questions": [
                {
                    "order": 1,
                    "question_id": "q1",
                    "type": "解答题",
                    "stem": r"已知 \(x^2+1\) 与集合{A}，求 \(x\) 的取值。",
                    "answer": r"x=1",
                    "analysis": r"略",
                }
            ],
        }
        tex = render_paper_latex(paper, include_stem=True, include_answer=False, include_analysis=False)
        # Math segments must remain intact.
        self.assertIn(r"\(x^2+1\)", tex)
        self.assertIn(r"\(x\)", tex)
        # Outside-math braces should still be escaped.
        self.assertIn(r"\{A\}", tex)
