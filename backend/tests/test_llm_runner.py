import unittest
from unittest.mock import AsyncMock, patch

from backend.llm.client import ChatCompletionResult


class TestLlmRunner(unittest.IsolatedAsyncioTestCase):
    async def test_run_text_resolves_retry_and_timeout_defaults(self) -> None:
        from backend.llm import runner

        fake_chat = AsyncMock(return_value=ChatCompletionResult(content="ok"))
        with patch("backend.llm.runner.chat_completion", new=fake_chat), patch.dict(
            "os.environ",
            {"TEST_LLM_RETRIES": "12", "TEST_LLM_TIMEOUT_S": "0.5"},
            clear=False,
        ):
            text = await runner.run_text(
                messages=[{"role": "user", "content": "hello"}],
                model="openai/test-mini",
                temperature=0.2,
                max_tokens=128,
                retry_env_vars=("TEST_LLM_RETRIES",),
                timeout_env_vars=("TEST_LLM_TIMEOUT_S",),
                max_retries=8,
                min_timeout_s=2.0,
                req_id_prefix="unit",
            )

        self.assertEqual(text, "ok")
        kwargs = fake_chat.await_args.kwargs
        self.assertEqual(kwargs["retries"], 8)
        self.assertEqual(kwargs["timeout_s"], 2.0)
        self.assertFalse(kwargs["raise_on_fail"])
        self.assertEqual(kwargs["req_id_prefix"], "unit")

    async def test_run_json_sets_json_response_format_and_parses_fenced_json(self) -> None:
        from backend.llm import runner

        fake_chat = AsyncMock(return_value=ChatCompletionResult(content='```json\n{"ok": true}\n```'))
        with patch("backend.llm.runner.chat_completion", new=fake_chat):
            obj = await runner.run_json(
                messages=[{"role": "user", "content": "json"}],
                model="openai/test-mini",
                temperature=0.1,
                max_tokens=256,
                req_id_prefix="json",
            )

        self.assertEqual(obj, {"ok": True})
        self.assertEqual(fake_chat.await_args.kwargs["response_format"], {"type": "json_object"})

    async def test_run_tool_use_preserves_tool_options(self) -> None:
        from backend.llm import runner

        fake_chat = AsyncMock(return_value=ChatCompletionResult(content="", tool_calls=[{"id": "tc1"}]))
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
        with patch("backend.llm.runner.chat_completion", new=fake_chat):
            res = await runner.run_tool_use(
                messages=[{"role": "user", "content": "use tool"}],
                model="openai/test-mini",
                temperature=0.1,
                max_tokens=256,
                tools=tools,
                tool_choice="auto",
                stream=True,
                raise_on_fail=True,
                retries=2,
                req_id_prefix="tools",
            )

        self.assertEqual(res.tool_calls, [{"id": "tc1"}])
        kwargs = fake_chat.await_args.kwargs
        self.assertEqual(kwargs["tools"], tools)
        self.assertEqual(kwargs["tool_choice"], "auto")
        self.assertTrue(kwargs["stream"])
        self.assertTrue(kwargs["raise_on_fail"])
