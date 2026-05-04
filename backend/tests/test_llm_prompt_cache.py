from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from backend.llm import client as llm_client


class LlmPromptCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await llm_client.close_shared_llm_http_client()

    async def asyncTearDown(self) -> None:
        await llm_client.close_shared_llm_http_client()

    async def test_cacheable_message_is_sent_and_cached_tokens_are_parsed(self) -> None:
        captured_payloads: list[dict] = []
        req = httpx.Request("POST", "https://example.test/chat/completions")

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def post(self, url, headers=None, json=None):  # noqa: ANN001,ANN201
                _ = url, headers
                captured_payloads.append(dict(json or {}))
                return httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                        "usage": {
                            "prompt_tokens": 20,
                            "completion_tokens": 1,
                            "prompt_tokens_details": {"cached_tokens": 12},
                        },
                    },
                    request=req,
                )

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient), patch.object(
            llm_client,
            "resolve_provider",
            return_value=("openrouter", "https://example.test", "key", "test-model"),
        ):
            res = await llm_client.chat_completion(
                messages=[
                    llm_client.cacheable_message("system", "stable system prompt"),
                    {"role": "user", "content": "hi"},
                ],
                model="test-model",
                temperature=0.2,
                max_tokens=20,
                retries=1,
                raise_on_fail=True,
            )

        self.assertEqual(res.content, "ok")
        self.assertEqual(res.cached_tokens, 12)
        self.assertEqual(captured_payloads[0]["messages"][0]["cache_control"], {"type": "ephemeral"})


if __name__ == "__main__":
    unittest.main()
