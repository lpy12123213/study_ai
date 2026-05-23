import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class TestMcpStdioTools(unittest.TestCase):
    def test_get_stdio_tools_contains_keyword_search(self) -> None:
        from backend.integrations.mcp.tools.stdio_tools import get_stdio_tools

        tools = get_stdio_tools()
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 5)

        names = {getattr(t, "name", "") for t in tools}
        self.assertIn("search_questions_by_keyword", names)

    def test_web_search_tool_schema_allows_tavily_provider(self) -> None:
        from backend.integrations.mcp.tools.stdio_tools import get_stdio_tools

        tool = next(t for t in get_stdio_tools() if getattr(t, "name", "") == "web_search")
        provider_schema = tool.inputSchema["properties"]["provider"]

        self.assertIn("tavily", provider_schema["enum"])


class TestMcpStdioHandlers(unittest.IsolatedAsyncioTestCase):
    async def test_web_search_auto_uses_tavily_when_configured(self) -> None:
        from backend.integrations.mcp.tools.stdio_handlers import handle_tool_call

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
                texts = await handle_tool_call(
                    object(),
                    "web_search",
                    {"query": "导数 新闻", "provider": "auto", "limit": 3},
                )

        payload = json.loads(texts[0].text)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["provider"], "tavily")
        self.assertEqual(payload["results"][0]["url"], "https://example.com/t")
        tavily_search.assert_awaited_once()

    async def test_llm_helper_prompts_use_registry(self) -> None:
        from backend.generation.agentic.prompts import create_default_prompt_registry
        from backend.integrations.mcp.tools.stdio_handlers import handle_tool_call

        captured: list[str] = []
        returns = [
            '{"definition":"d","key_points":[],"prerequisites":[],"common_mistakes":[],"methods":[]}',
            '{"outline":["o"],"confusions":[],"teaching_order":[]}',
            "## 讲解",
            "## 解答",
            '{"passed":true,"issues":[],"suggestions":[]}',
            "摘要",
        ]

        async def fake_call_llm_text(*, messages, **_kwargs):  # type: ignore[no-untyped-def]
            captured.append(str(messages[0]["content"]))
            return returns.pop(0)

        server = SimpleNamespace(current_subject="高中数学", crawler=None)
        registry = create_default_prompt_registry()

        with patch("backend.integrations.mcp.tools.stdio_handlers.LESSON_PLAN_API_KEY", "lp-key"):
            with patch("backend.integrations.mcp.tools.stdio_handlers.call_llm_text", new=fake_call_llm_text):
                await handle_tool_call(server, "retrieve_knowledge", {"topic": "导数"})
                await handle_tool_call(server, "analyze_topic", {"topic": "导数"})
                await handle_tool_call(server, "generate_explanation", {"topic": "导数"})
                await handle_tool_call(server, "generate_solution", {"stem": "1+1=?"})
                await handle_tool_call(server, "review_content", {"topic": "导数", "markdown": "正文"})
                await handle_tool_call(server, "compress_context", {"messages": [{"role": "user", "content": "hi"}]})

        self.assertEqual(
            captured,
            [
                registry.render("mcp.knowledge_facts.v1").content,
                registry.render("lesson_plan.activity_planner.v1").content,
                registry.render("mcp.study_section.v1").content,
                registry.render("mcp.solve_stepwise.v1").content,
                registry.render("mcp.review_study_material.v1").content,
                registry.render("mcp.context_summarize.v1").content,
            ],
        )


if __name__ == "__main__":
    unittest.main()
