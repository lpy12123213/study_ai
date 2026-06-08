from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api.auth import require_admin, require_auth
from backend.api.integrations.openai_adapter import router as openai_adapter_router
from backend.api.system import router as system_router
from backend.integrations.mcp.search import metaso
from backend.integrations.mcp.search.zhihu import ZhihuFetcher


def _raise_http(status_code: int, detail: str) -> None:
    raise HTTPException(status_code=status_code, detail=detail)


class OpenAIAdapterSecurityTests(unittest.TestCase):
    def _client(self) -> TestClient:
        app = FastAPI()
        app.include_router(openai_adapter_router, prefix="/integrations/openai")
        return TestClient(app)

    def test_adapter_routes_require_auth_dependency(self) -> None:
        app = FastAPI()
        app.include_router(openai_adapter_router, prefix="/integrations/openai")
        app.dependency_overrides[require_auth] = lambda: _raise_http(401, "auth_required")

        with patch(
            "backend.api.integrations.openai_adapter.list_papers",
            new=AsyncMock(return_value=[]),
        ):
            response = TestClient(app).get("/integrations/openai/papers")

        self.assertEqual(response.status_code, 401)

    def test_create_paper_uses_authenticated_user_id(self) -> None:
        app = FastAPI()
        app.include_router(openai_adapter_router, prefix="/integrations/openai")
        app.dependency_overrides[require_auth] = lambda: {
            "user_id": "user-from-token",
            "username": "alice",
            "role": "user",
        }

        save_paper = AsyncMock(return_value=123)
        with patch("backend.api.integrations.openai_adapter.save_paper", new=save_paper):
            response = TestClient(app).post(
                "/integrations/openai/create-paper",
                json={"paper_name": "安全回归", "question_ids": ["q1"]},
            )

        self.assertEqual(response.status_code, 200)
        save_paper.assert_awaited_once()
        self.assertEqual(save_paper.await_args.kwargs["user_id"], "user-from-token")


class SystemMetricsSecurityTests(unittest.TestCase):
    def test_metrics_requires_admin_dependency(self) -> None:
        app = FastAPI()
        app.include_router(system_router)
        app.dependency_overrides[require_admin] = lambda: _raise_http(403, "admin_required")

        with patch("backend.api.system.metrics_enabled", return_value=True), patch(
            "backend.api.system.generate_metrics",
            return_value=(b"metric 1\n", "text/plain; version=0.0.4"),
        ):
            response = TestClient(app).get("/metrics")

        self.assertEqual(response.status_code, 403)


class SearchFetchSSRFSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_zhihu_fetch_rejects_private_url_before_http(self) -> None:
        fetcher = ZhihuFetcher()
        get_html = AsyncMock(return_value="<html><title>internal</title></html>")

        with patch.object(fetcher, "_get_html", new=get_html):
            result = await fetcher.fetch("http://127.0.0.1/admin")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "forbidden_url")
        get_html.assert_not_awaited()

    async def test_metaso_reader_rejects_private_url_before_http(self) -> None:
        client_calls: list[str] = []

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
                client_calls.append("init")

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
                return None

            async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
                client_calls.append("post")
                return httpx.Response(200, text="internal text", request=httpx.Request("POST", "https://metaso.test/reader"))

        with patch("backend.integrations.mcp.search.metaso.METASO_API_KEY", "metaso-key"), patch(
            "backend.integrations.mcp.search.metaso.httpx.AsyncClient",
            FakeAsyncClient,
        ):
            result = await metaso.metaso_reader(url="http://127.0.0.1/admin")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "forbidden_url")
        self.assertEqual(client_calls, [])


if __name__ == "__main__":
    unittest.main()
