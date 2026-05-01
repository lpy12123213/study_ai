from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.mcp.search import tavily


class TestTavilySearch(unittest.IsolatedAsyncioTestCase):
    async def test_tavily_search_uses_bearer_auth_and_normalizes_results(self) -> None:
        captured: dict = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "answer": "answer",
                    "results": [
                        {
                            "title": "Result",
                            "url": "https://example.com/result",
                            "content": "snippet",
                            "raw_content": "full text",
                            "published_date": "2026-04-30",
                            "score": 0.9,
                        }
                    ],
                }

        class FakeClient:
            def __init__(self, *, timeout: float) -> None:
                captured["timeout"] = timeout

            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def post(self, url: str, *, headers: dict, json: dict) -> FakeResponse:
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                return FakeResponse()

        with patch.object(tavily, "TAVILY_API_KEY", "tvly-test"):
            with patch.object(tavily.httpx, "AsyncClient", FakeClient):
                result = await tavily.tavily_search(
                    "导数",
                    max_results=3,
                    include_answer=True,
                    include_raw_content=True,
                    topic="news",
                    days=30,
                )

        self.assertTrue(result["success"])
        self.assertEqual(captured["headers"]["Authorization"], "Bearer tvly-test")
        self.assertNotIn("api_key", captured["json"])
        self.assertEqual(captured["json"]["topic"], "news")
        self.assertEqual(captured["json"]["days"], 30)
        self.assertEqual(result["answer"], "answer")
        self.assertEqual(result["results"][0]["text"], "full text")
        self.assertEqual(result["results"][0]["snippet"], "snippet")
        self.assertEqual(result["results"][0]["published_date"], "2026-04-30")


if __name__ == "__main__":
    unittest.main()
