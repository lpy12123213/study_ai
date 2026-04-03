import unittest
from unittest.mock import patch

import httpx

from backend.llm import client as llm_client
from backend.llm import providers


class ResolveProviderTests(unittest.TestCase):
    def test_auto_switches_to_moonshot_for_moonshot_models(self) -> None:
        provider, base_url, api_key, model = providers.resolve_provider(
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1/",
            api_key="or-key",
            model="moonshotai/kimi-k2",
            moonshot_key="ms-key",
            moonshot_base_url="https://api.moonshot.cn/v1/",
        )

        self.assertEqual(provider, "moonshot")
        self.assertEqual(base_url, "https://api.moonshot.cn/v1")
        self.assertEqual(api_key, "ms-key")
        self.assertEqual(model, "kimi-k2")

    def test_keeps_openrouter_for_non_moonshot_models(self) -> None:
        provider, base_url, api_key, model = providers.resolve_provider(
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key="or-key",
            model="openai/gpt-4o-mini",
            moonshot_key="ms-key",
            moonshot_base_url="https://api.moonshot.cn/v1",
        )

        self.assertEqual(provider, "openrouter")
        self.assertEqual(base_url, "https://openrouter.ai/api/v1")
        self.assertEqual(api_key, "or-key")
        self.assertEqual(model, "openai/gpt-4o-mini")

    def test_explicit_moonshot_overrides_key_and_base_url(self) -> None:
        provider, base_url, api_key, model = providers.resolve_provider(
            provider="moonshot",
            base_url="https://openrouter.ai/api/v1",
            api_key="or-key",
            model="moonshotai/moonshot-v1-8k",
            moonshot_key="ms-key",
            moonshot_base_url="https://api.moonshot.cn/v1",
        )

        self.assertEqual(provider, "moonshot")
        self.assertEqual(base_url, "https://api.moonshot.cn/v1")
        self.assertEqual(api_key, "ms-key")
        self.assertEqual(model, "moonshot-v1-8k")


class RespErrorTests(unittest.TestCase):
    def test_resp_error_prefers_nested_error_message(self) -> None:
        resp = httpx.Response(
            400,
            json={"error": {"message": "bad request"}},
            request=httpx.Request("POST", "https://example.test"),
        )
        self.assertEqual(llm_client._resp_error(resp), "bad request")

    def test_resp_error_falls_back_to_detail(self) -> None:
        resp = httpx.Response(
            500,
            json={"detail": "something broke"},
            request=httpx.Request("POST", "https://example.test"),
        )
        self.assertEqual(llm_client._resp_error(resp), "something broke")

    def test_resp_error_falls_back_to_plain_text(self) -> None:
        resp = httpx.Response(
            502,
            text="bad gateway",
            request=httpx.Request("POST", "https://example.test"),
        )
        self.assertEqual(llm_client._resp_error(resp), "bad gateway")


class ApiKeyOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_lesson_plan_api_key = llm_client.LESSON_PLAN_API_KEY
        self._orig_moonshot_api_key = llm_client.MOONSHOT_API_KEY
        llm_client.LESSON_PLAN_API_KEY = ""
        llm_client.MOONSHOT_API_KEY = ""

    def tearDown(self) -> None:
        llm_client.LESSON_PLAN_API_KEY = self._orig_lesson_plan_api_key
        llm_client.MOONSHOT_API_KEY = self._orig_moonshot_api_key

    def test_is_llm_configured_false_without_env_or_override(self) -> None:
        self.assertFalse(llm_client.is_llm_configured())

    def test_is_llm_configured_true_with_llm_override(self) -> None:
        token = llm_client.set_llm_api_key_override("or-key")
        try:
            self.assertTrue(llm_client.is_llm_configured())
            self.assertEqual(llm_client.get_llm_api_key_override(), "or-key")
        finally:
            llm_client.reset_llm_api_key_override(token)

        self.assertFalse(llm_client.is_llm_configured())
        self.assertEqual(llm_client.get_llm_api_key_override(), "")

    def test_is_llm_configured_true_with_moonshot_override(self) -> None:
        token = llm_client.set_moonshot_api_key_override("ms-key")
        try:
            self.assertTrue(llm_client.is_llm_configured())
            self.assertEqual(llm_client.get_moonshot_api_key_override(), "ms-key")
        finally:
            llm_client.reset_moonshot_api_key_override(token)

        self.assertFalse(llm_client.is_llm_configured())
        self.assertEqual(llm_client.get_moonshot_api_key_override(), "")


class ChatCompletionReasoningCompatTests(unittest.IsolatedAsyncioTestCase):
    async def test_openrouter_deepseek_drops_reasoning_when_not_streaming(self) -> None:
        captured_payloads: list[dict] = []
        req = httpx.Request("POST", "https://example.test/chat/completions")
        responses = [
            httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]},
                request=req,
            )
        ]

        class _State:
            idx = 0

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def __aenter__(self):  # noqa: ANN201
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001,ANN201
                return False

            async def post(self, url, headers=None, json=None):  # noqa: ANN001,ANN201
                _ = url, headers
                captured_payloads.append(dict(json or {}))
                resp = responses[_State.idx]
                _State.idx += 1
                return resp

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient):
            res = await llm_client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                model="deepseek/deepseek-v3.2",
                temperature=0.2,
                max_tokens=50,
                response_format={"type": "json_object"},
                reasoning={"effort": "minimal", "exclude": True},
                stream=False,
                raise_on_fail=True,
                retries=1,
                req_id_prefix="test",
                provider="openrouter",
                base_url="https://example.test",
                api_key="or-key",
                moonshot_key="",
                moonshot_base_url="",
            )

        self.assertEqual(res.content, "ok")
        self.assertEqual(len(captured_payloads), 1)
        self.assertNotIn("reasoning", captured_payloads[0])

    async def test_empty_content_retries_without_reasoning(self) -> None:
        captured_payloads: list[dict] = []
        req = httpx.Request("POST", "https://example.test/chat/completions")
        responses = [
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": None}, "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
                request=req,
            ),
            httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]},
                request=req,
            ),
        ]

        class _State:
            idx = 0

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def __aenter__(self):  # noqa: ANN201
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001,ANN201
                return False

            async def post(self, url, headers=None, json=None):  # noqa: ANN001,ANN201
                _ = url, headers
                captured_payloads.append(dict(json or {}))
                resp = responses[_State.idx]
                _State.idx += 1
                return resp

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient):
            res = await llm_client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                model="openai/gpt-4o-mini",
                temperature=0.2,
                max_tokens=50,
                response_format=None,
                reasoning={"effort": "minimal", "exclude": True},
                stream=False,
                raise_on_fail=True,
                retries=2,
                req_id_prefix="test",
                provider="openrouter",
                base_url="https://example.test",
                api_key="or-key",
                moonshot_key="",
                moonshot_base_url="",
            )

        self.assertEqual(res.content, "ok")
        self.assertEqual(len(captured_payloads), 2)
        self.assertIn("reasoning", captured_payloads[0])
        self.assertNotIn("reasoning", captured_payloads[1])

    async def test_tool_calls_are_preserved_when_content_is_empty(self) -> None:
        captured_payloads: list[dict] = []
        req = httpx.Request("POST", "https://example.test/chat/completions")
        responses = [
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {"name": "mcp_web_search", "arguments": "{\"query\":\"函数方程\"}"},
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
                request=req,
            )
        ]

        class _State:
            idx = 0

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def __aenter__(self):  # noqa: ANN201
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001,ANN201
                return False

            async def post(self, url, headers=None, json=None):  # noqa: ANN001,ANN201
                _ = url, headers
                captured_payloads.append(dict(json or {}))
                resp = responses[_State.idx]
                _State.idx += 1
                return resp

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient):
            res = await llm_client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                model="openai/gpt-4o-mini",
                temperature=0.2,
                max_tokens=50,
                response_format=None,
                reasoning={"effort": "minimal", "exclude": True},
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "mcp_web_search",
                            "description": "search",
                            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                        },
                    }
                ],
                tool_choice="auto",
                stream=False,
                raise_on_fail=True,
                retries=1,
                req_id_prefix="test",
                provider="openrouter",
                base_url="https://example.test",
                api_key="or-key",
                moonshot_key="",
                moonshot_base_url="",
            )

        self.assertEqual(res.content, "")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0]["function"]["name"], "mcp_web_search")
        self.assertEqual(len(captured_payloads), 1)
        self.assertIn("tools", captured_payloads[0])


if __name__ == "__main__":
    unittest.main()
