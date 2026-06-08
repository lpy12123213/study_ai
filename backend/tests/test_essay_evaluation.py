"""Smoke tests for the essay-evaluation domain.

These cover the deterministic helpers (parser + scoring math + JSON
extraction) that don't require the LLM, so they run quickly inside
``unittest discover`` without external dependencies.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.generation.essay_evaluation.essay_parser import parse_essay
from backend.generation.essay_evaluation.essay_schemas import EssayEvaluationRequest, EssayScore
from backend.generation.essay_evaluation.service import (
    _normalize_paragraph_feedback,
    _normalize_scores,
    _safe_extract_json,
    _scale_to_total,
    _select_rubric,
    evaluate_essay,
)
from backend.llm.prompts import create_default_prompt_registry


class EssayParserTests(unittest.TestCase):
    def test_parses_paragraphs_and_counts_chars(self) -> None:
        text = "第一段开头。第一段第二句。\n\n第二段单句。"
        parsed = parse_essay(text)

        self.assertEqual(parsed.paragraph_count, 2)
        self.assertEqual(parsed.paragraphs[0].sentence_count, 2)
        self.assertEqual(parsed.paragraphs[1].sentence_count, 1)
        self.assertGreater(parsed.char_count, 0)
        self.assertEqual(parsed.language_hint, "zh")

    def test_detects_english_essay(self) -> None:
        text = "Education is the cornerstone of progress.\n\nIt empowers individuals."
        parsed = parse_essay(text)

        self.assertEqual(parsed.language_hint, "en")
        self.assertEqual(parsed.paragraph_count, 2)

    def test_empty_input_returns_zeroed_metrics(self) -> None:
        parsed = parse_essay("")
        self.assertEqual(parsed.paragraph_count, 0)
        self.assertEqual(parsed.char_count, 0)
        self.assertEqual(parsed.paragraphs, [])


class ScoringHelperTests(unittest.TestCase):
    def test_safe_extract_json_handles_code_fence(self) -> None:
        payload = """```json
        {"score_total": 42}
        ```"""
        self.assertEqual(_safe_extract_json(payload), {"score_total": 42})

    def test_safe_extract_json_returns_empty_on_invalid(self) -> None:
        self.assertEqual(_safe_extract_json("no json here"), {})

    def test_normalize_scores_fills_missing_dimensions_with_zero(self) -> None:
        rubric = _select_rubric("zh")
        scored = _normalize_scores([{"name": rubric[0]["name"], "score": 9}], rubric)

        self.assertEqual(len(scored), len(rubric))
        self.assertEqual(scored[0].score, 9)
        # Dimensions the LLM forgot fall back to zero rather than disappearing.
        self.assertEqual(scored[1].score, 0)

    def test_scale_to_total_clamps_within_target(self) -> None:
        rubric = _select_rubric("zh")
        scores = [
            EssayScore(name=item["name"], score=item["max_score"], max_score=item["max_score"], weight=item["weight"])
            for item in rubric
        ]
        total, max_score = _scale_to_total(scores, target_total=60)
        self.assertEqual(max_score, 60.0)
        self.assertAlmostEqual(total, 60.0, places=1)

    def test_scale_to_total_handles_partial_scores(self) -> None:
        rubric = _select_rubric("zh")
        scores = [
            EssayScore(name=item["name"], score=item["max_score"] / 2, max_score=item["max_score"], weight=item["weight"])
            for item in rubric
        ]
        total, max_score = _scale_to_total(scores, target_total=60)
        self.assertEqual(max_score, 60.0)
        self.assertGreater(total, 25.0)
        self.assertLess(total, 35.0)

    def test_normalize_paragraph_feedback_filters_out_of_range_indices(self) -> None:
        feedback = _normalize_paragraph_feedback(
            [
                {"index": 0, "issues": ["a"], "suggestion": "x"},
                {"index": 99, "issues": ["bad"]},  # dropped
                {"index": -1, "issues": ["bad"]},  # dropped
            ],
            max_index=2,
        )
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0].index, 0)


class EssayEvaluationPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_evaluate_essay_system_prompt_uses_registry(self) -> None:
        from backend.generation.essay_evaluation import service

        captured = {}
        rubric = service._select_rubric("zh")
        scores = [
            {
                "name": item["name"],
                "score": 8,
                "max_score": item["max_score"],
                "weight": item["weight"],
                "comment": "较好",
            }
            for item in rubric
        ]

        async def fake_chat_completion_text(**kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = kwargs["messages"]
            return service.json.dumps(
                {
                    "scores": scores,
                    "score_total": 48,
                    "summary": "结构完整，论证较清楚。",
                    "grade": "良好",
                    "strengths": ["结构清晰"],
                    "weaknesses": ["例证略少"],
                    "suggestions": ["补充具体例子"],
                    "paragraph_feedback": [],
                    "rewrite": "",
                },
                ensure_ascii=False,
            )

        request = EssayEvaluationRequest(
            text="第一段提出观点，说明学习需要坚持。\n\n第二段结合例子展开论证，并给出总结。",
            subject="语文",
            topic="坚持",
        )

        with patch.object(service, "is_llm_configured", return_value=True), patch.object(
            service,
            "chat_completion_text",
            new=fake_chat_completion_text,
        ):
            result = await evaluate_essay(request, model="dummy-model")

        self.assertEqual(
            captured["messages"][0]["content"],
            create_default_prompt_registry().render("essay.evaluate.system.v1").content,
        )
        self.assertEqual(result.grade, "良好")
        self.assertGreater(result.score_total, 0)


if __name__ == "__main__":
    unittest.main()
