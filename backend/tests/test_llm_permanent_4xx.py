from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend.llm import client as llm_client
from backend.llm.retry_policy import RetryPolicy

# Zero-delay policy so retry/adaptation paths stay exercised without real backoff sleeps.
FAST_POLICY = RetryPolicy(min_delay_s=0.0, base_delay_s=0.0, jitter_s=0.0, adaptation_delay_s=0.0)


def _ok_body() -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}


def _call_kwargs(**overrides):
    kwargs = {
        "messages": [{"role": "user", "content": "hi"}],
        "model": "test-model",
        "temperature": 0.2,
        "max_tokens": 20,
        "stream": False,
        "retries": 3,
        "req_id_prefix": "test",
        "provider": "ikuncode",
        "base_url": "https://example.test/v1",
        "api_key": "test-key",
        "moonshot_key": "",
        "moonshot_base_url": "",
    }
    kwargs.update(overrides)
    return kwargs


def _scripted_client(specs: list, calls: list):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
            pass

        async def aclose(self) -> None:
            return None

        async def post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001,ANN201
            _ = headers, timeout
            calls.append({"url": str(url), "json": dict(json or {})})
            status, body = specs[min(len(calls) - 1, len(specs) - 1)]
            return httpx.Response(status, json=body, request=httpx.Request("POST", str(url)))

    return FakeAsyncClient


class Permanent4xxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await llm_client.close_shared_llm_http_client()

    async def asyncTearDown(self) -> None:
        await llm_client.close_shared_llm_http_client()

    async def test_401_fails_fast_without_retry(self) -> None:
        calls: list = []
        specs = [(401, {"error": {"message": "invalid api key"}})] * 5

        with patch.object(llm_client.httpx, "AsyncClient", _scripted_client(specs, calls)), patch(
            "backend.llm.response_handlers.DEFAULT_RETRY_POLICY", FAST_POLICY
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await llm_client.chat_completion(**_call_kwargs(retries=5, raise_on_fail=True))

        self.assertIn("status=401", str(ctx.exception))
        self.assertIn("invalid api key", str(ctx.exception))
        self.assertEqual(len(calls), 1)

    async def test_403_fails_fast_without_retry(self) -> None:
        calls: list = []
        specs = [(403, {"error": {"message": "forbidden"}})] * 5

        with patch.object(llm_client.httpx, "AsyncClient", _scripted_client(specs, calls)), patch(
            "backend.llm.response_handlers.DEFAULT_RETRY_POLICY", FAST_POLICY
        ):
            res = await llm_client.chat_completion(**_call_kwargs(retries=5, raise_on_fail=False))

        self.assertEqual(res.error_code, "4xx")
        self.assertEqual(len(calls), 1)

    async def test_400_model_not_found_mutates_once_then_fails_fast(self) -> None:
        calls: list = []
        specs = [(400, {"error": {"message": "Model not found"}})] * 10

        with patch.object(llm_client.httpx, "AsyncClient", _scripted_client(specs, calls)), patch(
            "backend.llm.response_handlers.DEFAULT_RETRY_POLICY", FAST_POLICY
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await llm_client.chat_completion(
                    **_call_kwargs(
                        retries=5,
                        raise_on_fail=True,
                        response_format={"type": "json_object"},
                        reasoning={"effort": "low", "exclude": True},
                    )
                )

        # First 400 drops the optional fields once; the identical repeat 400 fails fast.
        self.assertEqual(len(calls), 2)
        self.assertIn("status=400", str(ctx.exception))
        self.assertIn("Model not found", str(ctx.exception))
        self.assertIn("response_format", calls[0]["json"])
        self.assertIn("reasoning", calls[0]["json"])
        self.assertNotIn("response_format", calls[1]["json"])
        self.assertNotIn("reasoning", calls[1]["json"])

    async def test_400_without_mutations_fails_in_one_call(self) -> None:
        calls: list = []
        specs = [(400, {"error": {"message": "Model not found"}})] * 10

        with patch.object(llm_client.httpx, "AsyncClient", _scripted_client(specs, calls)), patch(
            "backend.llm.response_handlers.DEFAULT_RETRY_POLICY", FAST_POLICY
        ):
            res = await llm_client.chat_completion(**_call_kwargs(retries=5, raise_on_fail=False))

        self.assertEqual(res.error_code, "4xx")
        self.assertEqual(len(calls), 1)

    async def test_400_repeated_mutation_error_does_not_burn_adaptive_budget(self) -> None:
        # Moonshot temperature-fix mutation is not flag-guarded: before the signature cap it
        # re-fired on every identical 400 until the adaptive budget/request cap ran out.
        calls: list = []
        specs = [(400, {"error": {"message": "temperature must be only 1"}})] * 10

        with patch.object(llm_client.httpx, "AsyncClient", _scripted_client(specs, calls)), patch(
            "backend.llm.response_handlers.DEFAULT_RETRY_POLICY", FAST_POLICY
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await llm_client.chat_completion(
                    **_call_kwargs(
                        retries=3,
                        raise_on_fail=True,
                        provider="moonshot",
                        base_url="https://api.moonshot.cn/v1",
                        api_key="ms-key",
                        model="moonshotai/moonshot-v1-8k",
                        moonshot_key="ms-key",
                        moonshot_base_url="https://api.moonshot.cn/v1",
                    )
                )

        self.assertIn("status=400", str(ctx.exception))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["json"]["temperature"], 0.2)
        self.assertEqual(calls[1]["json"]["temperature"], 1.0)

    async def test_429_still_retries_with_backoff(self) -> None:
        calls: list = []
        specs = [
            (429, {"error": {"message": "rate limited"}}),
            (429, {"error": {"message": "rate limited"}}),
            (200, _ok_body()),
        ]

        with patch.object(llm_client.httpx, "AsyncClient", _scripted_client(specs, calls)), patch(
            "backend.llm.response_handlers.DEFAULT_RETRY_POLICY", FAST_POLICY
        ):
            res = await llm_client.chat_completion(**_call_kwargs(retries=3, raise_on_fail=True))

        self.assertEqual(res.content, "ok")
        self.assertEqual(len(calls), 3)

    async def test_v1_append_rescue_still_works(self) -> None:
        calls: list = []
        specs = [
            (404, {"error": {"message": "Not found"}}),
            (200, _ok_body()),
        ]

        with patch.object(llm_client.httpx, "AsyncClient", _scripted_client(specs, calls)), patch(
            "backend.llm.response_handlers.DEFAULT_RETRY_POLICY", FAST_POLICY
        ):
            res = await llm_client.chat_completion(
                **_call_kwargs(retries=2, raise_on_fail=True, provider="custom", base_url="https://example.test")
            )

        self.assertEqual(res.content, "ok")
        self.assertEqual(
            [c["url"] for c in calls],
            ["https://example.test/chat/completions", "https://example.test/v1/chat/completions"],
        )

    async def test_v1_append_then_identical_404_fails_fast(self) -> None:
        calls: list = []
        specs = [(404, {"error": {"message": "Model not found"}})] * 10

        with patch.object(llm_client.httpx, "AsyncClient", _scripted_client(specs, calls)), patch(
            "backend.llm.response_handlers.DEFAULT_RETRY_POLICY", FAST_POLICY
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await llm_client.chat_completion(
                    **_call_kwargs(retries=5, raise_on_fail=True, provider="custom", base_url="https://example.test")
                )

        self.assertIn("status=404", str(ctx.exception))
        self.assertIn("Model not found", str(ctx.exception))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["url"], "https://example.test/v1/chat/completions")


class StudyMaterialsModelSelfCheckTests(unittest.TestCase):
    def test_self_check_skips_under_pytest_current_test(self) -> None:
        from backend import app as app_module

        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test_x (call)"}):
            self.assertFalse(app_module._study_materials_model_self_check_enabled())

    def test_self_check_env_opt_out(self) -> None:
        from backend import app as app_module

        with patch.dict(sys.modules) as modules, patch.dict(os.environ) as env:
            modules.pop("pytest", None)
            env.pop("PYTEST_CURRENT_TEST", None)
            env["STUDY_MATERIALS_MODEL_SELF_CHECK"] = "0"
            self.assertFalse(app_module._study_materials_model_self_check_enabled())
            env["STUDY_MATERIALS_MODEL_SELF_CHECK"] = "1"
            self.assertTrue(app_module._study_materials_model_self_check_enabled())


class StudyMaterialsModelSelfCheckPingTests(unittest.IsolatedAsyncioTestCase):
    async def test_self_check_logs_error_on_permanent_4xx(self) -> None:
        from backend import app as app_module
        from backend.core import settings as settings_mod
        from backend.llm.result import ChatCompletionResult

        mock_chat = AsyncMock(return_value=ChatCompletionResult(error_code="4xx"))
        with patch("backend.llm.client.chat_completion", new=mock_chat), patch.object(
            settings_mod, "STUDY_MATERIALS_THINKING_MODEL", "bad-thinking-model"
        ), patch.object(settings_mod, "STUDY_MATERIALS_WRITER_MODEL", "bad-writer-model"):
            with self.assertLogs("backend.app", level="ERROR") as logs:
                await app_module._study_materials_model_self_check()

        self.assertEqual(mock_chat.await_count, 2)
        self.assertTrue(any("study_materials_model_self_check_failed" in line for line in logs.output))
        self.assertTrue(
            any(getattr(r, "config", "") == "models.study_materials_thinking" for r in logs.records)
        )
        self.assertTrue(
            any("models.study_materials_thinking" in str(getattr(r, "hint", "")) for r in logs.records)
        )

    async def test_self_check_never_raises_on_unexpected_error(self) -> None:
        from backend import app as app_module
        from backend.core import settings as settings_mod

        mock_chat = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("backend.llm.client.chat_completion", new=mock_chat), patch.object(
            settings_mod, "STUDY_MATERIALS_THINKING_MODEL", "bad-thinking-model"
        ), patch.object(settings_mod, "STUDY_MATERIALS_WRITER_MODEL", "bad-writer-model"):
            # Must swallow provider/network surprises: startup self-check is best-effort.
            await app_module._study_materials_model_self_check()

        self.assertEqual(mock_chat.await_count, 2)


if __name__ == "__main__":
    unittest.main()
