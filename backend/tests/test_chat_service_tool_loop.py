from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any, Dict, List, Optional

from backend.workspace.chat.service import ChatService


def _tool_call(idx: int, name: str) -> Dict[str, Any]:
    return {
        "id": f"call_{idx}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps({"keyword": f"kp-{idx}"}, ensure_ascii=False)},
    }


class _FakeStreamingToolService(ChatService):
    def __init__(self, tool_names: List[str]) -> None:
        super().__init__()
        self.tool_names = tool_names
        self.api_calls: List[Dict[str, Any]] = []
        self.active_tools = 0
        self.max_active_tools = 0

    def _build_messages(self, history: List[Dict[str, Any]], user_message: str, subject: str) -> List[Dict[str, Any]]:
        return [{"role": "user", "content": user_message}]

    def _determine_tools_for_request(self, history: List[Dict[str, Any]], user_message: str):  # type: ignore[no-untyped-def]
        return []

    async def _call_api(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        include_tools: bool = True,
        tools_override: Optional[List[Dict[str, Any]]] = None,
        max_retries: int = 3,
        stream: bool = False,
        on_content_delta=None,  # type: ignore[no-untyped-def]
        on_reasoning_delta=None,  # type: ignore[no-untyped-def]
    ) -> Dict[str, Any]:
        self.api_calls.append(
            {
                "stream": stream,
                "include_tools": include_tools,
                "tools_override": tools_override,
                "max_retries": max_retries,
            }
        )
        if len(self.api_calls) == 1:
            if on_content_delta:
                await on_content_delta("planning")
            return {
                "success": True,
                "content": "planning",
                "tool_calls": [_tool_call(i, name) for i, name in enumerate(self.tool_names)],
            }

        if on_content_delta:
            await on_content_delta("final answer")
        return {"success": True, "content": "final answer", "tool_calls": []}

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        sub_model: Optional[str] = None,
        user_id: str,
    ) -> Dict[str, Any]:
        self.active_tools += 1
        self.max_active_tools = max(self.max_active_tools, self.active_tools)
        try:
            await asyncio.sleep(0.02)
            return {"success": True, "tool": tool_name, "arguments": arguments}
        finally:
            self.active_tools -= 1


class TestChatServiceToolLoop(unittest.IsolatedAsyncioTestCase):
    async def test_tool_decision_streams_and_executes_all_nonexclusive_tools_concurrently(self) -> None:
        service = _FakeStreamingToolService(["search_questions", "get_available_filters", "get_papers", "get_question_detail"])

        events = [
            event
            async for event in service.chat(
                [],
                "帮我找题",
                user_id="u1",
                subject="高中数学",
                model="test-model",
            )
        ]

        self.assertTrue(all(call["stream"] for call in service.api_calls))
        self.assertGreaterEqual(service.max_active_tools, 2)
        self.assertEqual(len([e for e in events if e.get("type") == "tool_start"]), 4)
        self.assertEqual(len([e for e in events if e.get("type") == "tool_result"]), 4)
        self.assertTrue(any(e.get("type") == "text_delta" and e.get("content") == "planning" for e in events))
        self.assertEqual(events[-1].get("type"), "assistant_final")
        self.assertEqual(events[-1].get("content"), "final answer")

    async def test_mutually_exclusive_tool_calls_run_sequentially(self) -> None:
        service = _FakeStreamingToolService(["search_questions", "create_paper"])

        _events = [
            event
            async for event in service.chat(
                [],
                "创建试卷",
                user_id="u1",
                subject="高中数学",
                model="test-model",
            )
        ]

        self.assertEqual(service.max_active_tools, 1)


if __name__ == "__main__":
    unittest.main()
