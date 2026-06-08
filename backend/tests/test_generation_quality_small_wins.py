from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch


class GenerationQualitySmallWinsTests(unittest.TestCase):
    def test_auto_planner_normalizes_points_total_when_possible(self) -> None:
        from backend.generation.paper_compose.auto_planner import _normalize_slot_points, _slot_points_total

        slots = [
            {"question_type": "选择题", "count": 10, "points_each": 3},
            {"question_type": "解答题", "count": 5, "points_each": 9},
        ]

        normalized, notes = _normalize_slot_points(slots, total_points=100)

        self.assertEqual(_slot_points_total(normalized), 100)
        self.assertTrue(any(note.startswith("score_total_normalized") for note in notes))

    def test_exporters_mark_ai_synthesized_answer_for_review(self) -> None:
        from backend.generation.paper_compose.exporters import docx, latex, markdown

        paper = {
            "paper_name": "测试卷",
            "questions": [
                {
                    "question_id": "q1",
                    "type": "解答题",
                    "stem": "求解。",
                    "answer": "x=1",
                    "analysis": "移项。",
                    "answer_source": "ai_synthesis",
                }
            ],
        }

        md = markdown.render_paper_markdown(paper, include_stem=True, include_answer=True, include_analysis=True)
        tex = latex.render_paper_latex(paper, include_stem=True, include_answer=True, include_analysis=True)

        self.assertIn(markdown.AI_SYNTHESIS_REVIEW_NOTE, md)
        self.assertIn("AI", tex)
        self.assertEqual(docx.AI_SYNTHESIS_REVIEW_NOTE, markdown.AI_SYNTHESIS_REVIEW_NOTE)

    def test_markdown_export_escapes_pipe_in_metadata_table(self) -> None:
        from backend.generation.paper_compose.exporters.markdown import render_paper_markdown

        paper = {
            "paper_name": "测试卷",
            "questions": [
                {
                    "question_id": "q|1",
                    "type": "选择|题",
                    "knowledge_point": "函|数",
                    "source_url": "https://example.test/a|b",
                }
            ],
        }

        out = render_paper_markdown(paper)

        self.assertIn("选择\\|题", out)
        self.assertIn("函\\|数", out)
        self.assertIn("q\\|1", out)

    def test_stem_fingerprint_normalizes_punctuation_and_numbers(self) -> None:
        from backend.generation.paper_compose.workflow_support import _stem_fingerprint

        fp1 = _stem_fingerprint("已知 x = 12, 求 f(12) 的值？")
        fp2 = _stem_fingerprint("已知x=987，求 f(987) 的值!")

        self.assertEqual(fp1, fp2)
        self.assertEqual(len(fp1), 32)

    def test_latex_export_renders_options_missing_image_and_hides_internal_id(self) -> None:
        from backend.generation.paper_compose.exporters.latex import render_paper_latex

        paper = {
            "paper_name": "测试卷",
            "questions": [
                {
                    "question_id": "secret-internal-id",
                    "type": "选择题",
                    "stem": "如图，选择正确结论。",
                    "options": ["A. 甲", "B. 乙", "C. 丙"],
                    "diagrams": [{"url": ""}],
                },
                {"question_id": "another-secret-id", "type": "解答题", "stem": ""},
            ],
        }

        tex = render_paper_latex(paper, include_stem=True)

        self.assertIn(r"\begin{enumerate}", tex)
        self.assertIn(r"\item", tex)
        self.assertIn("图示缺失", tex)
        self.assertIn("题干暂缺", tex)
        self.assertNotIn("secret-internal-id", tex)
        self.assertNotIn("another-secret-id", tex)

    def test_answer_synthesis_limit_is_independent_from_ai_question_limit(self) -> None:
        from backend.generation.paper_compose.workflow import _resolve_answer_synthesis_limit

        self.assertEqual(_resolve_answer_synthesis_limit({}, ai_question_limit=3), 50)
        self.assertEqual(_resolve_answer_synthesis_limit({"maxAnswerSynthesisItems": 7}, ai_question_limit=3), 7)

    def test_knowledge_type_prefers_algorithm_for_solution_methods(self) -> None:
        from backend.agent.tools.knowledge import knowledge_type_detection, study_material_generation

        self.assertEqual(knowledge_type_detection._heuristic_type("一元二次方程解法"), "algorithm")
        self.assertEqual(study_material_generation._heuristic_knowledge_type("一元二次方程解法"), "algorithm")

    def test_sanitize_explanation_markdown_removes_empty_parentheses_after_url_cleanup(self) -> None:
        from backend.agent.tools.utils.text_utils import _sanitize_explanation_markdown

        out = _sanitize_explanation_markdown("详见(https://example.test/a)。", knowledge_point="导数")

        self.assertNotIn("()", out)
        self.assertIn("详见。", out)


class GenerationQualitySmallWinsAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_review_error_marks_needs_human_instead_of_pass(self) -> None:
        from backend.generation.paper_compose import auto_review

        question = {
            "question_id": "ai_error",
            "type": "解答题",
            "stem": "求解 x+1=2。",
            "answer": "x=1",
            "analysis": "移项。",
            "source": "ai_generate_full",
        }

        with patch.object(auto_review, "solve_draft", new=AsyncMock(side_effect=RuntimeError("boom"))), patch.object(
            auto_review.logger,
            "warning",
        ):
            result = await auto_review.review_questions([question], subject="高中数学", topic="函数")

        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(question["review_status"], "needs_human")
        self.assertEqual(question["review_action"], "needs_human")
        self.assertEqual(result["items"][0]["mode"], "review_error")

    async def test_numeric_verification_flags_failed_check_without_blocking(self) -> None:
        from backend.generation.paper_compose import numeric_verification

        question = {
            "question_id": "calc-1",
            "type": "解答题",
            "stem": "计算 2+2。",
            "answer": "5",
            "analysis": "2+2=5。",
            "verification_code": "result = (2 + 2 == 5)",
        }

        compute = AsyncMock(return_value={"success": True, "result_repr": "False", "stdout": ""})
        with patch.object(numeric_verification, "python_scientific_compute", new=compute):
            result = await numeric_verification.verify_numeric_answers([question], enabled=True, max_items=5)

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertIn("numeric_verification_failed", question["quality_flags"])
        self.assertEqual(question["review_status"], "needs_human")
        self.assertEqual(question["review_action"], "needs_human")
        compute.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
