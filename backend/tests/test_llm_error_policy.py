from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from backend.llm import client as llm_client


class TestLLMErrorPolicy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await llm_client.close_shared_llm_http_client()

    async def asyncTearDown(self) -> None:
        await llm_client.close_shared_llm_http_client()

    async def test_chat_completion_raises_by_default_when_not_configured(self) -> None:
        with patch.object(
            llm_client,
            "resolve_provider",
            return_value=("openrouter", "https://example.test", "", "test-model"),
        ):
            with self.assertRaisesRegex(RuntimeError, "llm_not_configured"):
                await llm_client.chat_completion(
                    messages=[{"role": "user", "content": "hi"}],
                    model="test-model",
                    temperature=0.2,
                    max_tokens=20,
                )

            res = await llm_client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                model="test-model",
                temperature=0.2,
                max_tokens=20,
                raise_on_fail=False,
            )

        self.assertEqual(res.error_code, "not_configured")

    async def test_chat_completion_returns_classified_error_code_when_fallback_allowed(self) -> None:
        req = httpx.Request("POST", "https://example.test/chat/completions")

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def post(self, url, headers=None, json=None):  # noqa: ANN001,ANN201
                _ = url, headers, json
                return httpx.Response(429, json={"error": {"message": "rate limited"}}, request=req)

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient), patch.object(
            llm_client,
            "resolve_provider",
            return_value=("openrouter", "https://example.test", "key", "test-model"),
        ):
            res = await llm_client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                model="test-model",
                temperature=0.2,
                max_tokens=20,
                retries=1,
                raise_on_fail=False,
            )

        self.assertEqual(res.error_code, "4xx")


if __name__ == "__main__":
    unittest.main()
