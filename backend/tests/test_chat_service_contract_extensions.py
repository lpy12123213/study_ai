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
    """与 test_chat_service_tool_loop 相同形状的可控服务：只替换 LLM 与工具执行。"""

    def __init__(self, tool_names: List[str], tool_sleep_s: float = 0.02) -> None:
        super().__init__()
        self.tool_names = tool_names
        self.tool_sleep_s = tool_sleep_s
        self.api_calls: List[Dict[str, Any]] = []
        self.executed_tools: List[str] = []
        self.on_tool_execute = None

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
        self.api_calls.append({"tools_override": tools_override})
        if len(self.api_calls) == 1:
            return {
                "success": True,
                "content": "planning",
                "tool_calls": [_tool_call(i, name) for i, name in enumerate(self.tool_names)],
            }
        return {"success": True, "content": "final answer", "tool_calls": []}

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        sub_model: Optional[str] = None,
        user_id: str,
    ) -> Dict[str, Any]:
        self.executed_tools.append(tool_name)
        if self.on_tool_execute is not None:
            self.on_tool_execute(tool_name)
        await asyncio.sleep(self.tool_sleep_s)
        return {"success": True, "tool": tool_name}


async def _collect(service: ChatService, **kwargs: Any) -> List[Dict[str, Any]]:
    return [event async for event in service.chat([], "帮我找题", user_id="u1", subject="高中数学", **kwargs)]


class TestToolTimingAndExecutionMode(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_batch_declares_execution_mode_and_server_timing(self) -> None:
        service = _FakeStreamingToolService(["search_questions", "get_papers", "web_search"])
        events = await _collect(service, model="test-model")

        starts = [e for e in events if e.get("type") == "tool_start"]
        results = [e for e in events if e.get("type") == "tool_result"]
        self.assertEqual(len(starts), 3)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(e.get("execution_mode") == "parallel" for e in starts))
        self.assertTrue(all(e.get("execution_mode") == "parallel" for e in results))
        for e in results:
            self.assertIsInstance(e.get("elapsed_ms"), int)
            self.assertGreaterEqual(e["elapsed_ms"], 0)
            self.assertIsInstance(e.get("started_at"), float)
            self.assertIsInstance(e.get("finished_at"), float)
            self.assertGreaterEqual(e["finished_at"], e["started_at"])

    async def test_mutually_exclusive_batch_declares_sequential(self) -> None:
        service = _FakeStreamingToolService(["search_questions", "create_paper"])
        events = await _collect(service, model="test-model")

        starts = [e for e in events if e.get("type") == "tool_start"]
        results = [e for e in events if e.get("type") == "tool_result"]
        self.assertEqual(len(starts), 2)
        self.assertTrue(all(e.get("execution_mode") == "sequential" for e in starts))
        self.assertTrue(all(e.get("execution_mode") == "sequential" for e in results))


class TestChatCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_before_start_yields_cancelled_only(self) -> None:
        service = _FakeStreamingToolService(["search_questions"])
        cancel_event = asyncio.Event()
        cancel_event.set()

        events = await _collect(service, model="test-model", cancel_event=cancel_event)

        self.assertEqual([e.get("type") for e in events], ["cancelled"])
        self.assertEqual(service.api_calls, [])

    async def test_cancel_during_sequential_batch_stops_before_next_tool(self) -> None:
        service = _FakeStreamingToolService(["search_questions", "create_paper"])
        cancel_event = asyncio.Event()
        # 第一个工具执行中请求取消：当前工具完整结束并发出 tool_result，第二个不再开始
        service.on_tool_execute = lambda name: cancel_event.set()

        events = await _collect(service, model="test-model", cancel_event=cancel_event)
        types = [e.get("type") for e in events]

        self.assertEqual(types.count("tool_start"), 2)
        self.assertEqual(types.count("tool_result"), 1)
        self.assertIn("cancelled", types)
        self.assertNotIn("assistant_final", types)
        self.assertEqual(service.executed_tools, ["search_questions"])

    async def test_cancel_during_parallel_batch_interrupts_gather(self) -> None:
        service = _FakeStreamingToolService(["search_questions", "get_papers"], tool_sleep_s=0.5)
        cancel_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        service.on_tool_execute = lambda name: loop.call_later(0.05, cancel_event.set)

        events = await _collect(service, model="test-model", cancel_event=cancel_event)
        types = [e.get("type") for e in events]

        self.assertEqual(types.count("tool_start"), 2)
        self.assertEqual(types.count("tool_result"), 0)
        self.assertEqual(types[-1], "cancelled")


class TestStructuredIntent(unittest.IsolatedAsyncioTestCase):
    HISTORY_WITH_PLAN = [
        {
            "role": "assistant",
            "content": '方案如下 <EXAM_PAPER_PLAN>{"slots": [{"type": "选择题"}]}</EXAM_PAPER_PLAN>',
        }
    ]

    def test_confirm_intent_with_plan_opens_full_toolset(self) -> None:
        service = ChatService()
        full = service._determine_tools_for_intent(self.HISTORY_WITH_PLAN, "confirm_create_paper")
        base = service._determine_tools_for_intent(self.HISTORY_WITH_PLAN, "revise_plan")
        names_full = {t["function"]["name"] for t in full}
        names_base = {t["function"]["name"] for t in base}
        self.assertIn("create_paper", names_full)
        self.assertNotIn("create_paper", names_base)

    def test_confirm_intent_without_plan_stays_base(self) -> None:
        service = ChatService()
        tools = service._determine_tools_for_intent([], "confirm_create_paper")
        names = {t["function"]["name"] for t in tools}
        self.assertNotIn("create_paper", names)

    async def test_chat_passes_intent_to_tool_determination(self) -> None:
        service = _FakeStreamingToolService([])
        seen: Dict[str, Any] = {}

        def _fake_intent_tools(history: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
            seen["intent"] = intent
            return []

        service._determine_tools_for_intent = _fake_intent_tools  # type: ignore[method-assign]
        await _collect(service, model="test-model", intent="confirm_create_paper")
        self.assertEqual(seen.get("intent"), "confirm_create_paper")


class TestConfirmationNegationGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ChatService()

    def test_plain_confirmations_still_match(self) -> None:
        for msg in ("确认", "可以", "好的，开始吧", "ok", "确认，请按方案创建"):
            self.assertTrue(self.service._is_confirmation_message(msg), msg)

    def test_negated_confirmations_do_not_match(self) -> None:
        for msg in ("不可以", "不要开始", "别开始", "先不确认", "不好的方案"):
            self.assertFalse(self.service._is_confirmation_message(msg), msg)

    def test_mixed_message_with_real_confirmation_matches(self) -> None:
        # 同一消息里既有否定又有独立确认词：独立命中仍算确认
        self.assertTrue(self.service._is_confirmation_message("不要改题量，确认创建"))


if __name__ == "__main__":
    unittest.main()
