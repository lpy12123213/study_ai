import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class TestAgentReActDecision(unittest.IsolatedAsyncioTestCase):
    def _make_loop(self):
        from backend.agent.config import AgentConfig
        from backend.agent.mcp.registry import MCPToolRegistry
        from backend.agent.react.loop import ReActLoop

        return ReActLoop(
            config=AgentConfig(planner_model="test-planner"),
            tool_registry=MCPToolRegistry(),
        )

    async def test_llm_decide_prefers_tool_call_schema(self) -> None:
        from backend.agent.react.loop import REACT_DECISION_TOOL

        calls = []

        async def fake_chat_completion(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "react_decision",
                            "arguments": json.dumps(
                                {
                                    "thought": "Use retrieval first.",
                                    "action": "web_search_knowledge",
                                    "batch_mode": "per_knowledge_point",
                                    "arguments": {"knowledge_points": ["KP-1"]},
                                    "note": "",
                                }
                            ),
                        },
                    }
                ],
            )

        loop = self._make_loop()
        with patch("backend.agent.react.loop.is_llm_configured", return_value=True), patch(
            "backend.agent.react.loop.chat_completion",
            side_effect=fake_chat_completion,
        ):
            decision = await loop._llm_decide([{"role": "system", "content": "decide"}])

        self.assertEqual(decision["action"], "web_search_knowledge")
        self.assertEqual(decision["arguments"], {"knowledge_points": ["KP-1"]})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tools"], [REACT_DECISION_TOOL])
        self.assertEqual(calls[0]["tool_choice"]["function"]["name"], "react_decision")
        self.assertNotIn("response_format", calls[0])

    async def test_llm_decide_falls_back_to_validated_json(self) -> None:
        calls = []

        async def fake_chat_completion(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(
                    content="",
                    tool_calls=[
                        {
                            "type": "function",
                            "function": {
                                "name": "react_decision",
                                "arguments": "{not json}",
                            },
                        }
                    ],
                )
            return SimpleNamespace(
                content=json.dumps({"thought": "Finish now.", "action": "finish", "arguments": {}}),
                tool_calls=[],
            )

        loop = self._make_loop()
        with patch("backend.agent.react.loop.is_llm_configured", return_value=True), patch(
            "backend.agent.react.loop.chat_completion",
            side_effect=fake_chat_completion,
        ):
            decision = await loop._llm_decide([{"role": "system", "content": "decide"}])

        self.assertEqual(decision["action"], "finish")
        self.assertEqual(decision["arguments"], {})
        self.assertEqual(len(calls), 2)
        self.assertIn("tools", calls[0])
        self.assertEqual(calls[1]["response_format"], {"type": "json_object"})
        self.assertIn("invalid react_decision tool call", calls[1]["messages"][-1]["content"])
        self.assertNotIn("tools", calls[1])

    async def test_llm_decide_rejects_json_without_action(self) -> None:
        calls = []

        async def fake_chat_completion(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content=json.dumps({"thought": "No action", "arguments": {}}), tool_calls=[])

        loop = self._make_loop()
        with patch("backend.agent.react.loop.is_llm_configured", return_value=True), patch(
            "backend.agent.react.loop.chat_completion",
            side_effect=fake_chat_completion,
        ):
            decision = await loop._llm_decide([{"role": "system", "content": "decide"}])

        self.assertEqual(decision, {})
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
