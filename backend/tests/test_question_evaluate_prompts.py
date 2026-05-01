from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.generation.agentic.prompts import create_default_prompt_registry


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


if __name__ == "__main__":
    unittest.main()
