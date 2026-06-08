from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.workspace.chat.service import ChatService


class ChatExtraToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_python_scientific_compute_handler_reuses_mcp_implementation(self) -> None:
        from backend.workspace.chat.extra_tools import handle_python_scientific_compute

        compute = AsyncMock(return_value={"success": True, "result_repr": "4", "stdout": ""})

        with patch("backend.workspace.chat.extra_tools.python_scientific_compute", compute):
            result = await handle_python_scientific_compute(
                {"code": "2 + 2", "purpose": "check arithmetic", "timeout_seconds": 3},
                user_id="user-1",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["result_repr"], "4")
        compute.assert_awaited_once_with(code="2 + 2", purpose="check arithmetic", timeout_seconds=3)

    async def test_plot_function_handler_uses_request_user_id_and_returns_markdown(self) -> None:
        from backend.workspace.chat.extra_tools import handle_plot_function

        render = AsyncMock(
            return_value={
                "success": True,
                "url": "/api/media/generated/plot.svg",
                "markdown": "![plot](/api/media/generated/plot.svg)",
                "filename": "plot.svg",
                "cached": False,
                "bytes": 123,
            }
        )

        with patch("backend.workspace.chat.extra_tools.render_matplotlib_2d_to_url", render):
            result = await handle_plot_function(
                {"expr": "x**2 - 2*x", "x_range": [-1, 3], "title": "Quadratic", "label": "f(x)"},
                user_id="real-user",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["markdown"], "![plot](/api/media/generated/plot.svg)")
        call_kwargs = render.await_args.kwargs
        self.assertEqual(call_kwargs["user_id"], "real-user")
        self.assertEqual(call_kwargs["alt"], "plot")
        self.assertEqual(call_kwargs["spec"]["curves"][0]["expr"], "x**2 - 2*x")
        self.assertEqual(call_kwargs["spec"]["curves"][0]["label"], "f(x)")

    async def test_web_search_handler_formats_markdown_links(self) -> None:
        from backend.workspace.chat.extra_tools import handle_web_search

        search = AsyncMock(
            return_value={
                "success": True,
                "provider": "tavily",
                "query": "quadratic formula",
                "results": [
                    {
                        "title": "Quadratic formula",
                        "url": "https://example.com/quadratic",
                        "snippet": "A short summary.",
                        "published_date": "2026-01-01",
                    }
                ],
            }
        )

        with patch("backend.workspace.chat.extra_tools.run_web_search", search):
            result = await handle_web_search(
                {"query": "quadratic formula", "limit": 2, "provider": "auto"},
                user_id="user-1",
            )

        self.assertTrue(result["success"])
        self.assertIn("[Quadratic formula](https://example.com/quadratic)", result["markdown"])
        self.assertIn("A short summary.", result["markdown"])
        search.assert_awaited_once()
        self.assertEqual(search.await_args.kwargs["query"], "quadratic formula")
        self.assertEqual(search.await_args.kwargs["limit"], 2)

    async def test_shared_web_search_returns_config_error_without_provider_key(self) -> None:
        from backend.integrations.mcp.search.service import run_web_search

        with patch("backend.integrations.mcp.search.service._provider_has_key", return_value=False):
            result = await run_web_search("missing keys", provider="auto", limit=3)

        self.assertFalse(result["success"])
        self.assertEqual(result["results"], [])
        self.assertIn("API key", result["error"])

    async def test_mcp_web_search_handler_delegates_to_shared_service(self) -> None:
        from backend.integrations.mcp.tools.stdio_handlers import handle_tool_call

        search = AsyncMock(
            return_value={
                "success": True,
                "provider": "tavily",
                "query": "derivative news",
                "results": [{"title": "Result", "url": "https://example.com", "snippet": "snippet"}],
            }
        )

        with patch("backend.integrations.mcp.tools.stdio_handlers.run_web_search", search):
            texts = await handle_tool_call(
                SimpleNamespace(current_subject="High School Math", crawler=None),
                "web_search",
                {"query": "derivative news", "provider": "auto", "limit": 4, "mode": "trending", "recency_days": 30},
            )

        payload = json.loads(texts[0].text)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["results"][0]["url"], "https://example.com")
        search.assert_awaited_once()
        self.assertEqual(search.await_args.kwargs["query"], "derivative news")
        self.assertEqual(search.await_args.kwargs["limit"], 4)
        self.assertEqual(search.await_args.kwargs["mode"], "trending")

    def test_chat_tool_specs_and_visibility_include_extra_tools(self) -> None:
        service = ChatService()
        names = service._chat_tool_registry().names()

        self.assertIn("python_scientific_compute", names)
        self.assertIn("plot_function", names)
        self.assertIn("web_search", names)

        visible = [tool["function"]["name"] for tool in service._determine_tools_for_request([], "calculate and search")]
        self.assertIn("get_available_filters", visible)
        self.assertIn("search_questions", visible)
        self.assertIn("python_scientific_compute", visible)
        self.assertIn("plot_function", visible)
        self.assertIn("web_search", visible)


if __name__ == "__main__":
    unittest.main()
