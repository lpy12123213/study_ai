import unittest
from unittest.mock import AsyncMock, patch

from backend.generation.question_library.scoring import (
    extract_thinking_depth,
    score_question_batch_with_thinking_depth,
    score_stem_with_llm,
)
from backend.llm.prompts import create_default_prompt_registry


class TestQuestionLibraryScoreLlm(unittest.IsolatedAsyncioTestCase):
    async def test_score_parses_json(self) -> None:
        fake = {
            "verdict": "好题",
            "overall_score": 85,
            "dimensions": [{"name": "思维含量", "score": 9, "comment": "ok"}],
            "highlights": ["清晰"],
            "issues": [],
            "summary": "good",
        }
        captured = {}

        async def fake_run_json(**kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = kwargs["messages"]
            return fake

        with patch("backend.generation.question_library.scoring.run_json", new=AsyncMock(side_effect=fake_run_json)):
            out = await score_stem_with_llm(subject="高中数学", stem="题干", model="dummy")

        self.assertEqual(
            captured["messages"][0]["content"],
            create_default_prompt_registry().render("question.score.single_quality.v1").content,
        )
        self.assertEqual(out["overall_score"], 85)
        self.assertEqual(out["verdict"], "好题")

    async def test_score_stem_tolerates_non_integer_overall_score(self) -> None:
        async def fake_run_json(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return {
                "verdict": "普通题",
                "overall_score": "85分",
                "dimensions": [],
                "highlights": [],
                "issues": [],
                "summary": "score text from model",
            }

        with patch("backend.generation.question_library.scoring.run_json", new=AsyncMock(side_effect=fake_run_json)):
            out = await score_stem_with_llm(subject="高中数学", stem="题干", model="dummy")

        self.assertEqual(out["overall_score"], 0)
        self.assertEqual(out["verdict"], "普通题")

    async def test_batch_score_parses_thinking_depth_and_passes_method_context(self) -> None:
        captured = {}

        async def fake_run_json(**kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = kwargs["messages"]
            return {
                "items": [
                    {
                        "question_id": "q1",
                        "verdict": "好题",
                        "overall_score": 88,
                        "thinking_depth_score": 9,
                        "method_family": "构造辅助圆",
                        "method_signature": "用辅助圆转化角度关系",
                        "method_rarity": "rare",
                        "similar_method_count": 2,
                        "summary": "思路小众且有转化价值",
                    }
                ],
                "method_summary": [
                    {
                        "method_family": "构造辅助圆",
                        "count": 2,
                        "example_question_ids": ["q1"],
                    }
                ],
            }

        with patch("backend.generation.question_library.scoring.run_json", new=AsyncMock(side_effect=fake_run_json)):
            out = await score_question_batch_with_thinking_depth(
                subject="高中数学",
                questions=[{"question_id": "q1", "stem": "题干 1"}],
                model="dummy",
                method_context=[{"method_family": "常规代入", "count": 24}],
            )

        prompt_text = str(captured["messages"])
        self.assertIn("常规代入", prompt_text)
        self.assertEqual(
            captured["messages"][0]["content"],
            create_default_prompt_registry().render("question.score.thinking_depth_batch.v1").content,
        )
        self.assertEqual(out["items"][0]["thinking_depth_score"], 9)
        self.assertEqual(out["items"][0]["method_family"], "构造辅助圆")
        self.assertEqual(out["method_summary"][0]["count"], 2)

        depth = extract_thinking_depth(out["items"][0]["dimensions"])
        self.assertEqual(depth["score"], 9)
        self.assertEqual(depth["method_family"], "构造辅助圆")
