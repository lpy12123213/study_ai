"""executor._call_llm 的结构化输出 max_tokens 地板测试。

推理恒开模型（如 deepseek-v4 系列）的隐藏 reasoning tokens 计入 max_tokens：
900 之类的小上限会被思考吃光导致空/截断 JSON（线上事故：writer_review_failed: invalid_json）。
_executor 对 json_object 调用抬高 max_tokens 下限（AGENT_STRUCTURED_JSON_MIN_TOKENS，默认 3000）。
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.agent.executor import Executor


class StructuredJsonMaxTokensFloorTests(unittest.IsolatedAsyncioTestCase):
    async def _capture_max_tokens(self, *, response_format, max_tokens: int) -> int:
        chat = AsyncMock(return_value=object())
        with patch("backend.agent.executor.chat_completion", chat):
            await Executor()._call_llm(
                messages=[{"role": "user", "content": "hi"}],
                model="test-model",
                temperature=0.1,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        return chat.await_args.kwargs["max_tokens"]

    async def test_json_object_small_cap_is_floored(self) -> None:
        got = await self._capture_max_tokens(response_format={"type": "json_object"}, max_tokens=900)
        self.assertEqual(got, 3000)

    async def test_json_object_larger_cap_kept(self) -> None:
        got = await self._capture_max_tokens(response_format={"type": "json_object"}, max_tokens=8000)
        self.assertEqual(got, 8000)

    async def test_non_structured_call_unchanged(self) -> None:
        got = await self._capture_max_tokens(response_format=None, max_tokens=900)
        self.assertEqual(got, 900)

    async def test_floor_env_override(self) -> None:
        with patch.dict("os.environ", {"AGENT_STRUCTURED_JSON_MIN_TOKENS": "5000"}):
            got = await self._capture_max_tokens(response_format={"type": "json_object"}, max_tokens=900)
        self.assertEqual(got, 5000)


if __name__ == "__main__":
    unittest.main()
