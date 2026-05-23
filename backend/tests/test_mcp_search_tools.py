from __future__ import annotations

# ruff: noqa: E402,I001

# ---- from backend/tests/test_mcp_tavily.py ----
import unittest
from unittest.mock import AsyncMock, patch

from backend.integrations.mcp.search import tavily
from backend.integrations.mcp.search._base import FunctionSearchProvider, list_search_providers
from backend.integrations.mcp.search.registry import PROVIDERS


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
            async def post(self, url: str, *, headers: dict, json: dict, timeout: float) -> FakeResponse:
                captured["timeout"] = timeout
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                return FakeResponse()

        with patch.object(tavily, "TAVILY_API_KEY", "tvly-test"):
            with patch.object(tavily, "get_mcp_search_http_client", new=AsyncMock(return_value=FakeClient())):
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

    async def test_search_provider_registry_exposes_default_adapters(self) -> None:
        expected = {
            "bigmodel",
            "exa",
            "github",
            "mediawiki",
            "metaso",
            "stackexchange",
            "tavily",
            "wikipedia",
            "zhihu",
        }

        self.assertTrue(expected.issubset(set(PROVIDERS)))
        self.assertTrue(expected.issubset(set(list_search_providers())))
        self.assertIs(tavily.PROVIDER, PROVIDERS["tavily"])

    async def test_function_search_provider_normalizes_results(self) -> None:
        async def fake_search(query: str, limit: int) -> dict:
            return {
                "success": True,
                "results": [
                    {"title": f"{query} title", "url": "https://example.com/a", "summary": "summary", "score": "0.5"}
                    for _ in range(limit + 2)
                ],
            }

        provider = FunctionSearchProvider("fake", fake_search)
        hits = await provider.search("topic", limit=2)

        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]["provider"], "fake")
        self.assertEqual(hits[0]["snippet"], "summary")
        self.assertEqual(hits[0]["score"], 0.5)


if __name__ == "__main__":
    unittest.main()


# ---- from backend/tests/test_mcp_python_scientific_compute.py ----

import unittest

from backend.integrations.mcp.tools.python_scientific_compute import python_scientific_compute


class PythonScientificComputeTests(unittest.IsolatedAsyncioTestCase):
    async def test_executes_basic_math_and_returns_result(self) -> None:
        result = await python_scientific_compute(
            code="""
x = 3
y = 4
result = (x ** 2 + y ** 2) ** 0.5
""".strip()
        )

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("result_repr"), "5.0")
        self.assertEqual(result.get("result_type"), "float")

    async def test_uses_last_expression_when_result_not_assigned(self) -> None:
        result = await python_scientific_compute(
            code="""
import math
math.factorial(6)
""".strip()
        )

        self.assertFalse(result.get("success"))
        self.assertIn("不允许", str(result.get("error") or ""))

        result = await python_scientific_compute(
            code="""
math.factorial(6)
""".strip()
        )

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("result_repr"), "720")
        self.assertEqual(result.get("result_type"), "int")

    async def test_captures_stdout(self) -> None:
        result = await python_scientific_compute(
            code="""
print('intermediate=', 42)
result = 7 * 8
""".strip()
        )

        self.assertTrue(result.get("success"))
        self.assertIn("intermediate= 42", str(result.get("stdout") or ""))
        self.assertEqual(result.get("result_repr"), "56")

    async def test_supports_basic_function_def(self) -> None:
        result = await python_scientific_compute(
            code="""
def hypotenuse(a, b):
    return (a ** 2 + b ** 2) ** 0.5

result = hypotenuse(5, 12)
""".strip()
        )

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("result_repr"), "13.0")
        self.assertIn("hypotenuse", list(result.get("available_names") or []))

    async def test_rejects_function_annotations(self) -> None:
        result = await python_scientific_compute(
            code="""
def square(x: float) -> float:
    return x * x

result = square(3)
""".strip()
        )

        self.assertFalse(result.get("success"))
        self.assertIn("类型标注", str(result.get("error") or ""))

    async def test_rejects_extended_dangerous_builtins(self) -> None:
        for source in ("type('X', (object,), {})", "memoryview(b'abc')", "bytearray(b'abc')"):
            result = await python_scientific_compute(code=source)
            self.assertFalse(result.get("success"), source)
            self.assertIn("不允许调用", str(result.get("error") or ""))


if __name__ == "__main__":
    unittest.main()


# ---- from backend/tests/test_mcp_github.py ----


import unittest

from backend.integrations.mcp.search import github


class TestGitHubSearch(unittest.IsolatedAsyncioTestCase):
    async def test_github_search_repositories_normalizes_items(self) -> None:
        captured: dict = {}

        class FakeResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "total_count": 1,
                    "items": [
                        {
                            "full_name": "owner/repo",
                            "html_url": "https://github.com/owner/repo",
                            "description": "A repo",
                            "stargazers_count": 42,
                            "language": "Python",
                            "updated_at": "2026-05-01T00:00:00Z",
                            "default_branch": "main",
                        }
                    ],
                }

        class FakeClient:
            async def get(
                self,
                url: str,
                *,
                params: dict | None = None,
                headers: dict | None = None,
                timeout: float | None = None,
                follow_redirects: bool | None = None,
            ) -> FakeResponse:
                captured["url"] = url
                captured["params"] = params
                captured["headers"] = headers
                captured["timeout"] = timeout
                captured["follow_redirects"] = follow_redirects
                return FakeResponse()

        with patch.object(github, "get_mcp_search_http_client", new=AsyncMock(return_value=FakeClient())):
            result = await github.github_search_repositories("calculus", limit=2, token="gh-test")

        self.assertTrue(result["success"])
        self.assertEqual(captured["params"]["q"], "calculus")
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["results"][0]["full_name"], "owner/repo")
        self.assertEqual(result["results"][0]["stars"], 42)


if __name__ == "__main__":
    unittest.main()
