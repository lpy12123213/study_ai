import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from backend.cli import question_generate
from backend.cli.question_generate import review as question_generate_review


class CliMcpSearchModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_search_materials_uses_ikuncode_gpt_model_by_default(self) -> None:
        captured_models: list[str] = []

        async def fake_chat_completion(**kwargs):  # type: ignore[no-untyped-def]
            captured_models.append(str(kwargs.get("model") or ""))
            return type("Result", (), {"content": "done", "tool_calls": []})()

        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(question_generate.helpers, "settings", create=True),
            patch.object(question_generate.mcp_tools, "chat_completion", side_effect=fake_chat_completion),
            patch.object(
                question_generate.mcp_tools,
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
            question_generate.helpers.settings.chat_provider = "ikuncode"
            question_generate.helpers.settings.lesson_plan_provider = "ikuncode"
            question_generate.helpers.settings.main_model = "gpt-5.2"
            question_generate.helpers.settings.lesson_plan_model = "gpt-5.2"
            question_generate.helpers.settings.chat_base_url = "https://api.ikuncode.cc/v1"
            question_generate.helpers.settings.lesson_plan_base_url = "https://api.ikuncode.cc/v1"

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

    async def test_exec_mcp_web_search_tool_auto_uses_tavily_when_configured(self) -> None:
        tavily_search = AsyncMock(
            return_value={
                "success": True,
                "provider": "tavily",
                "query": "导数 新闻",
                "results": [
                    {"title": "Tavily result", "url": "https://example.com/t", "snippet": "snippet"},
                ],
            }
        )

        with patch("backend.integrations.mcp.search.tavily.TAVILY_API_KEY", "tvly-test"):
            with patch("backend.integrations.mcp.search.tavily.tavily_search", tavily_search):
                result = await question_generate._exec_mcp_web_search_tool(
                    query="导数 新闻",
                    limit=3,
                    provider="auto",
                    mode="trending",
                    recency_days=30,
                )

        self.assertTrue(result["success"])
        self.assertEqual(result["provider"], "tavily")
        self.assertEqual(result["results"][0]["url"], "https://example.com/t")
        tavily_search.assert_awaited_once()

    async def test_export_markdown_creates_parent_directory_for_explicit_path(self) -> None:
        session = {
            "user_id": "u-1",
            "session_id": "s-1",
            "subject": "高中数学",
            "topic": "导数",
            "draft_questions": [
                {
                    "question_id": "q-1",
                    "stem": "题干",
                    "answer": "答案",
                    "analysis": "解析",
                    "review_status": "approved",
                }
            ],
        }

        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "exports" / "questions.md"
            with patch.object(question_generate_review, "load_session", return_value=session):
                out = await question_generate_review._export_markdown(user_id="u-1", session_id="s-1", path=str(target))

            self.assertEqual(out, target.resolve())
            self.assertTrue(target.exists())
            self.assertIn("q-1", target.read_text(encoding="utf-8"))


class CliMcpSearchModelResolveTests(unittest.TestCase):
    def test_resolve_cli_mcp_search_model_prefers_configured_model_for_non_ikuncode(self) -> None:
        with (
            patch.dict(os.environ, {"QUESTION_LIBRARY_MCP_SEARCH_MODEL": ""}, clear=False),
            patch.object(question_generate.helpers, "settings", create=True),
        ):
            question_generate.helpers.settings.chat_provider = "openrouter"
            question_generate.helpers.settings.lesson_plan_provider = "openrouter"
            question_generate.helpers.settings.main_model = "anthropic/claude-3.7-sonnet"
            question_generate.helpers.settings.lesson_plan_model = "anthropic/claude-3.7-sonnet"

            model = question_generate._resolve_cli_mcp_search_model()

        self.assertEqual(model, "anthropic/claude-3.7-sonnet")
