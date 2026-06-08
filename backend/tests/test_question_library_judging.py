import unittest
from unittest.mock import AsyncMock, patch

from backend.generation.question_library.judging import judge_draft


class TestQuestionLibraryJudging(unittest.IsolatedAsyncioTestCase):
    async def test_judge_draft_tolerates_non_integer_scores(self) -> None:
        async def fake_chat_json_with_reasoning(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return (
                '{"pass": true, "verdict": "普通题", "overall_score": "高", '
                '"dimensions": [], "highlights": [], "issues": [], "summary": "ok", '
                '"difficulty_estimate": "中等", "novelty_score": "8.5", "reasoning_depth": "深"}'
            )

        with (
            patch("backend.generation.question_library.judging.is_llm_configured", return_value=True),
            patch(
                "backend.generation.question_library.judging._chat_json_with_reasoning",
                new=AsyncMock(side_effect=fake_chat_json_with_reasoning),
            ),
        ):
            out = await judge_draft(
                {"stem": "题干", "answer": "2", "analysis": "计算。"},
                {"subject": "高中数学", "difficulty": "中等"},
            )

        self.assertTrue(out["pass"])
        self.assertEqual(out["overall_score"], 0)
        self.assertEqual(out["novelty_score"], 0)
        self.assertEqual(out["reasoning_depth"], 0)


if __name__ == "__main__":
    unittest.main()
