from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.llm.prompts import create_default_prompt_registry


class QuestionEvaluatePromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_question_evaluate_prompt_uses_registry(self) -> None:
        from backend.api.question_evaluate import _evaluate_one
        from backend.api.question_evaluate_schemas import QuestionInput

        captured = {}

        async def fake_chat_completion_text(*, messages, **_kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = messages
            return '{"verdict":"好题","overall_score":88,"dimensions":[],"highlights":[],"issues":[],"summary":"ok"}'

        with patch("backend.api.question_evaluate.chat_completion_text", new=fake_chat_completion_text):
            result = await _evaluate_one(
                QuestionInput(question_id="q1", stem="1+1=?"),
                subject="高中数学",
                requirements="",
                model="test-model",
            )

        self.assertEqual(result.verdict, "好题")
        self.assertEqual(
            captured["messages"][0]["content"],
            create_default_prompt_registry().render("question.evaluate.external.v1").content,
        )

    async def test_generated_question_review_prompt_uses_registry(self) -> None:
        from backend.api.question_evaluate import evaluate_generated_question_review

        captured = {}

        async def fake_chat_completion_text(*, messages, **_kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = messages
            return '{"verdict":"普通题","overall_score":70,"dimensions":[],"highlights":[],"issues":[],"summary":"ok"}'

        with patch("backend.api.question_evaluate.chat_completion_text", new=fake_chat_completion_text):
            result = await evaluate_generated_question_review(
                subject="高中数学",
                stem="1+1=?",
                answer="2",
                analysis="计算。",
                model="test-model",
            )

        self.assertEqual(result["verdict"], "普通题")
        self.assertEqual(
            captured["messages"][0]["content"],
            create_default_prompt_registry().render("question.judge.quality.v1").content,
        )

    async def test_question_evaluate_batch_filters_failed_items(self) -> None:
        from backend.api.question_evaluate_schemas import QuestionEvaluation, QuestionInput
        from backend.generation.question_evaluate.service import evaluate_questions_batch

        async def fake_evaluate_one_question(q, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            if q.question_id == "bad":
                raise RuntimeError("llm_parse_failed")
            return QuestionEvaluation(
                question_id=q.question_id,
                verdict="好题",
                overall_score=90 if q.question_id == "best" else 70,
            )

        questions = [
            QuestionInput(question_id="ok", stem="1+1=?"),
            QuestionInput(question_id="bad", stem="bad"),
            QuestionInput(question_id="best", stem="2+2=?"),
        ]
        with patch(
            "backend.generation.question_evaluate.service.evaluate_one_question",
            new=fake_evaluate_one_question,
        ):
            results = await evaluate_questions_batch(
                questions=questions,
                subject="高中数学",
                requirements="",
                model="test-model",
            )

        self.assertEqual([item.question_id for item in results], ["best", "ok"])


if __name__ == "__main__":
    unittest.main()
