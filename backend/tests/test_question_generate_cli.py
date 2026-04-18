import os
import unittest
from unittest.mock import AsyncMock, patch

from backend.cli import question_generate


class CliMcpSearchModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_search_materials_uses_ikuncode_gpt_model_by_default(self) -> None:
        captured_models: list[str] = []

        async def fake_chat_completion(**kwargs):  # type: ignore[no-untyped-def]
            captured_models.append(str(kwargs.get("model") or ""))
            return type("Result", (), {"content": "done", "tool_calls": []})()

        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(question_generate, "settings", create=True),
            patch.object(question_generate, "chat_completion", side_effect=fake_chat_completion),
            patch.object(
                question_generate,
                "_exec_mcp_web_search_tool",
                AsyncMock(
                    return_value={
                        "success": True,
                        "provider": "exa",
                        "results": [
                            {
                                "title": "demo",
                                "url": "https://example.test/1",
                                "published_date": "2026-04-12",
                            }
                        ],
                    }
                ),
            ),
        ):
            question_generate.settings.chat_provider = "ikuncode"
            question_generate.settings.lesson_plan_provider = "ikuncode"
            question_generate.settings.main_model = "gpt-5.2"
            question_generate.settings.lesson_plan_model = "gpt-5.2"
            question_generate.settings.chat_base_url = "https://api.ikuncode.cc/v1"
            question_generate.settings.lesson_plan_base_url = "https://api.ikuncode.cc/v1"

            with patch.dict(os.environ, {"QUESTION_LIBRARY_MCP_SEARCH_MODEL": ""}, clear=False):
                out = await question_generate._ai_search_materials_via_mcp(
                    subject="高中数学",
                    topic="导数",
                    difficulty="中等",
                    question_type="解答题",
                    query="",
                    provider="auto",
                    mode="trending",
                    recency_days=30,
                    limit=3,
                    ui_log_tool=None,
                )

        self.assertTrue(out["success"])
        self.assertGreaterEqual(len(captured_models), 1)
        self.assertTrue(all(model == "gpt-5.2" for model in captured_models))
