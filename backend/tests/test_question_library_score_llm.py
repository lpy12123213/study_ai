import unittest
from unittest.mock import AsyncMock, patch

from backend.question_library.scoring import score_stem_with_llm


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
        with patch("backend.question_library.scoring.run_json", new=AsyncMock(return_value=fake)):
            out = await score_stem_with_llm(subject="高中数学", stem="题干", model="dummy")
        self.assertEqual(out["overall_score"], 85)
        self.assertEqual(out["verdict"], "好题")
