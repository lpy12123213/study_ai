from __future__ import annotations

import unittest

from backend.generation.agentic.task_adapter import (
    agent_trace_to_task_event,
    progress_from_agent_event,
)
from backend.generation.agentic.types import AgentTraceEvent


class AgenticTaskAdapterTests(unittest.TestCase):
    def test_agent_trace_event_converts_to_existing_task_event_shape(self) -> None:
        trace = AgentTraceEvent(
            event="agent_decision",
            role="planner",
            step_id="p1",
            data={"thought": "需要先检索", "action": "web_search_knowledge"},
        )

        event = agent_trace_to_task_event(trace, seq=8)

        self.assertEqual(event["seq"], 8)
        self.assertEqual(event["event"], "agent_decision")
        self.assertEqual(event["data"]["role"], "planner")
        self.assertEqual(event["data"]["step_id"], "p1")
        self.assertEqual(event["data"]["action"], "web_search_knowledge")

    def test_progress_can_be_derived_from_agent_events(self) -> None:
        self.assertEqual(progress_from_agent_event(AgentTraceEvent(event="tool_call")), 25)
        self.assertEqual(progress_from_agent_event(AgentTraceEvent(event="quality_gate")), 70)
        self.assertEqual(progress_from_agent_event(AgentTraceEvent(event="artifact")), 85)
        self.assertEqual(progress_from_agent_event(AgentTraceEvent(event="finish")), 100)

    def test_error_event_is_user_visible(self) -> None:
        trace = AgentTraceEvent(event="error", data={"error": "tool_budget_exceeded"})

        event = agent_trace_to_task_event(trace)

        self.assertEqual(event["event"], "error")
        self.assertEqual(event["data"]["error"], "tool_budget_exceeded")


if __name__ == "__main__":
    unittest.main()
