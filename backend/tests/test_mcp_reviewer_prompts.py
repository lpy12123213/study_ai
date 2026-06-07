from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.generation.agentic.prompts import create_default_prompt_registry


class McpReviewerPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_question_reviewer_uses_registry_system_prompt(self) -> None:
        from backend.integrations.mcp.tools import reviewer

        captured = {}

        async def fake_chat_completion(**kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = kwargs["messages"]
            return SimpleNamespace(content="Overall score: 8/10\nVerdict: APPROVE")

        with patch("backend.integrations.mcp.tools.reviewer.OPENROUTER_API_KEY", "or-key"):
            with patch("backend.integrations.mcp.tools.reviewer.REVIEW_PROVIDER", "openrouter"):
                with patch("backend.integrations.mcp.tools.reviewer.chat_completion", new=fake_chat_completion):
                    result = await reviewer.review_question(stem="1+1=?", subject="数学")

        self.assertEqual(result["verdict"], "APPROVE")
        self.assertEqual(
            captured["messages"][0]["content"],
            create_default_prompt_registry().render("mcp.question_reviewer.v1").content,
        )

    async def test_paper_reviewer_uses_registry_system_prompt(self) -> None:
        from backend.integrations.mcp.tools import reviewer

        captured = {}

        async def fake_chat_completion(**kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = kwargs["messages"]
            return SimpleNamespace(content="审查通过")

        questions = [{"question_id": "q1", "stem": "1+1=?", "type": "填空题", "difficulty": 0.5}]

        with patch("backend.integrations.mcp.tools.reviewer.OPENROUTER_API_KEY", "or-key"):
            with patch("backend.integrations.mcp.tools.reviewer.REVIEW_PROVIDER", "openrouter"):
                with patch("backend.integrations.mcp.tools.reviewer.chat_completion", new=fake_chat_completion):
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
        self.assertEqual(
            captured["messages"][1]["content"],
            reviewer._render_prompt(
                "mcp.paper_reviewer.user.v1",
                paper_info="Paper name: 测试卷\n",
                subject_info="Subject: 高中数学\n",
                question_count=1,
                strictness=3,
                strictness_desc="balanced: point out errors, problems, and improvement suggestions",
                focus_text="""
## User special requirements (priority)
**检查是否超纲**
Focus on the user requirements above during the review and respond to them first at the beginning of the report.
""",
                questions_text="""
【第1题】
- ID: q1
- 题型: 填空题
- 难度系数: 0.5
- 知识点: 未知
- 题干: 1+1=?
""",
            ),
        )
        self.assertIn("检查是否超纲", captured["messages"][1]["content"])

    async def test_sub_ai_selector_uses_registry_user_prompt(self) -> None:
        from backend.integrations.mcp.core import sub_ai_selector

        captured = {}

        async def fake_chat_completion(**kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = kwargs["messages"]
            return SimpleNamespace(
                content='{"selected_index":1,"selected_question_id":"q1","reason":"难度匹配","analysis":"唯一候选"}'
            )

        questions = [
            {
                "question_id": "q1",
                "stem": "1+1=?",
                "type": "填空题",
                "difficulty": 0.5,
                "knowledge_points": "导数",
            }
        ]
        questions_text = """
【题目1】
- ID: q1
- 题型: 填空题
- 难度系数: 0.5
- 知识点: 导数
- 题干内容: 1+1=?
"""

        with patch("backend.integrations.mcp.core.sub_ai_selector.is_llm_configured", return_value=True):
            with patch("backend.integrations.mcp.core.sub_ai_selector.chat_completion", new=fake_chat_completion):
                result = await sub_ai_selector.select_best_question(questions, "选择中等难度题")

        self.assertTrue(result["success"])
        self.assertEqual(
            captured["messages"][0]["content"],
            create_default_prompt_registry().render(
                "mcp.sub_ai_selector.user.v1",
                requirement="选择中等难度题",
                questions_count=1,
                questions_text=questions_text,
            ).content,
        )


if __name__ == "__main__":
    unittest.main()
