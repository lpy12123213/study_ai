from __future__ import annotations

import inspect
import os
import unittest
from unittest.mock import patch

from backend.chat.llm_mixin import ChatLLMMixin
from backend.chat.prompts import get_system_prompt
from backend.llm.client import _estimate_messages_tokens


class TestChatLLMMixinStreamingCleanup(unittest.TestCase):
    def test_streaming_cleanup_does_not_catch_base_exception(self) -> None:
        source = inspect.getsource(ChatLLMMixin._call_api_streaming)

        self.assertIn("asyncio.wait_for", source)
        self.assertNotIn("except BaseException", source)


class TestChatLLMMixinContextBudget(unittest.TestCase):
    def test_build_messages_uses_token_budget_for_history_selection(self) -> None:
        mixin = ChatLLMMixin()
        subject = "高中数学"
        user_message = "继续"
        base_tokens = _estimate_messages_tokens(
            [
                {"role": "system", "content": get_system_prompt(subject)},
                {"role": "user", "content": user_message},
            ]
        )

        with patch.dict(
            os.environ,
            {
                "CHAT_CONTEXT_MAX_TOKENS": str(base_tokens + 40),
                "CHAT_CONTEXT_MESSAGE_MAX_TOKENS": "2000",
            },
            clear=False,
        ):
            messages = mixin._build_messages(
                [
                    {"role": "user", "content": "早期内容" * 2000},
                    {"role": "assistant", "content": "最近回答"},
                ],
                user_message,
                subject,
            )

        contents = [str(m.get("content") or "") for m in messages]
        self.assertIn("最近回答", contents)
        self.assertFalse(any("早期内容" in c for c in contents))
        self.assertTrue(any("Omitted messages" in c for c in contents))

    def test_build_messages_clips_single_message_by_token_budget(self) -> None:
        mixin = ChatLLMMixin()
        with patch.dict(os.environ, {"CHAT_CONTEXT_MESSAGE_MAX_TOKENS": "128"}, clear=False):
            clipped = mixin._clip_context_text_to_budget("复杂概念" * 1000, max_chars=50_000, max_tokens=128, role="user")

        self.assertTrue(clipped.endswith("…"))
        self.assertLessEqual(_estimate_messages_tokens([{"role": "user", "content": clipped}]), 128)
