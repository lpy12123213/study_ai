from __future__ import annotations

import unittest
from unittest.mock import patch

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
            def __init__(self, **kwargs: object) -> None:
                captured["kwargs"] = kwargs

            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def get(self, url: str, *, params: dict | None = None) -> FakeResponse:
                captured["url"] = url
                captured["params"] = params
                return FakeResponse()

        with patch.object(github.httpx, "AsyncClient", FakeClient):
            result = await github.github_search_repositories("calculus", limit=2, token="gh-test")

        self.assertTrue(result["success"])
        self.assertEqual(captured["params"]["q"], "calculus")
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["results"][0]["full_name"], "owner/repo")
        self.assertEqual(result["results"][0]["stars"], 42)


if __name__ == "__main__":
    unittest.main()
