import unittest

import httpx

from backend.core import llm_client


class ResolveProviderTests(unittest.TestCase):
    def test_auto_switches_to_moonshot_for_moonshot_models(self) -> None:
        provider, base_url, api_key, model = llm_client._resolve_provider(
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
        provider, base_url, api_key, model = llm_client._resolve_provider(
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
        provider, base_url, api_key, model = llm_client._resolve_provider(
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


if __name__ == "__main__":
    unittest.main()
