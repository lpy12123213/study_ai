from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.generation.agentic.prompts import create_default_prompt_registry


class McpReviewerPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_question_reviewer_uses_registry_system_prompt(self) -> None:
        from backend.mcp.tools import reviewer

        captured = {}

        async def fake_chat_completion(**kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = kwargs["messages"]
            return SimpleNamespace(content="Overall score: 8/10\nVerdict: APPROVE")

        with patch("backend.mcp.tools.reviewer.OPENROUTER_API_KEY", "or-key"):
            with patch("backend.mcp.tools.reviewer.REVIEW_PROVIDER", "openrouter"):
                with patch("backend.mcp.tools.reviewer.chat_completion", new=fake_chat_completion):
                    result = await reviewer.review_question(stem="1+1=?", subject="数学")

        self.assertEqual(result["verdict"], "APPROVE")
        self.assertEqual(
            captured["messages"][0]["content"],
            create_default_prompt_registry().render("mcp.question_reviewer.v1").content,
        )

    async def test_paper_reviewer_uses_registry_system_prompt(self) -> None:
        from backend.mcp.tools import reviewer

        captured = {}

        async def fake_chat_completion(**kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = kwargs["messages"]
            return SimpleNamespace(content="审查通过")

        questions = [{"question_id": "q1", "stem": "1+1=?", "type": "填空题", "difficulty": 0.5}]

        with patch("backend.mcp.tools.reviewer.OPENROUTER_API_KEY", "or-key"):
            with patch("backend.mcp.tools.reviewer.REVIEW_PROVIDER", "openrouter"):
                with patch("backend.mcp.tools.reviewer.chat_completion", new=fake_chat_completion):
                    result = await reviewer.review_questions_with_openrouter(
                        questions,
                        paper_name="测试卷",
                        subject="高中数学",
                        focus="检查是否超纲",
                    )

        self.assertTrue(result["success"])
        self.assertEqual(
            captured["messages"][0]["content"],
            create_default_prompt_registry().render("mcp.paper_reviewer.v1").content,
        )
        self.assertIn("检查是否超纲", captured["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
