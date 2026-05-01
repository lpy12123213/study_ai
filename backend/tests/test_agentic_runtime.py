from __future__ import annotations

import asyncio
import unittest
from typing import Any, Dict, List

from backend.generation.agentic.runtime import AgentRuntime
from backend.generation.agentic.tooling import AgentDecision, ToolResult
from backend.generation.agentic.types import AgentArtifactRef, AgentBudget, AgentRunSpec, AgentToolPolicy


class SequencePlanner:
    def __init__(self, decisions: List[AgentDecision]) -> None:
        self.decisions = list(decisions)
        self.calls = 0

    async def next_decision(self, *, spec: AgentRunSpec, state: Dict[str, Any]) -> AgentDecision:
        self.calls += 1
        if self.decisions:
            return self.decisions.pop(0)
        return AgentDecision.finish(summary="done")


class RecordingToolExecutor:
    def __init__(self, results: List[ToolResult]) -> None:
        self.results = list(results)
        self.calls: List[Dict[str, Any]] = []

    async def execute_tool(self, *, name: str, arguments: Dict[str, Any], spec: AgentRunSpec, state: Dict[str, Any]) -> ToolResult:
        self.calls.append({"name": name, "arguments": dict(arguments)})
        if self.results:
            return self.results.pop(0)
        return ToolResult(success=True, output={"ok": True})


class CancelingToolExecutor:
    async def execute_tool(self, *, name: str, arguments: Dict[str, Any], spec: AgentRunSpec, state: Dict[str, Any]) -> ToolResult:
        raise asyncio.CancelledError()


def make_spec(*, budget: AgentBudget | None = None) -> AgentRunSpec:
    return AgentRunSpec(
        domain="study_materials",
        goal="生成自学资料",
        subject="高中数学",
        input_payload={"topic": "函数"},
        tool_policy=AgentToolPolicy(allowed_tools=["web_search_knowledge"]),
        budget=budget or AgentBudget(max_llm_calls=5, max_tool_calls=5, max_iterations=5),
    )


class AgenticRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_emits_ordered_trace_events(self) -> None:
        planner = SequencePlanner(
            [
                AgentDecision.tool(
                    name="web_search_knowledge",
                    arguments={"topic": "函数"},
                    thought="先检索",
                    role="researcher",
                    step_id="s1",
                ),
                AgentDecision.finish(summary="完成"),
            ]
        )
        executor = RecordingToolExecutor([ToolResult(success=True, output={"results": [1]})])
        runtime = AgentRuntime(planner=planner, tool_executor=executor)

        events = [event async for event in runtime.run(make_spec())]

        self.assertEqual([event.event for event in events], ["agent_decision", "tool_call", "tool_result", "finish"])
        self.assertEqual(events[0].role, "researcher")
        self.assertEqual(executor.calls[0]["arguments"]["topic"], "函数")

    async def test_runtime_respects_tool_budget(self) -> None:
        planner = SequencePlanner(
            [
                AgentDecision.tool(name="web_search_knowledge", arguments={"topic": "a"}, step_id="s1"),
                AgentDecision.tool(name="web_search_knowledge", arguments={"topic": "b"}, step_id="s2"),
            ]
        )
        executor = RecordingToolExecutor([ToolResult(success=True, output={})])
        runtime = AgentRuntime(planner=planner, tool_executor=executor)

        result = await runtime.run_to_result(make_spec(budget=AgentBudget(max_llm_calls=5, max_tool_calls=1, max_iterations=5)))

        self.assertEqual(result.status, "failed")
        self.assertIn("tool_budget_exceeded", result.error)
        self.assertEqual(len(executor.calls), 1)

    async def test_failed_tool_can_trigger_retry_with_changed_arguments(self) -> None:
        planner = SequencePlanner(
            [
                AgentDecision.tool(name="web_search_knowledge", arguments={"query": "old"}, step_id="s1"),
                AgentDecision.tool(name="web_search_knowledge", arguments={"query": "new"}, step_id="s2"),
                AgentDecision.finish(summary="完成"),
            ]
        )
        executor = RecordingToolExecutor(
            [
                ToolResult(success=False, error="empty_results"),
                ToolResult(success=True, output={"results": [1]}),
            ]
        )
        runtime = AgentRuntime(planner=planner, tool_executor=executor)

        events = [event async for event in runtime.run(make_spec())]

        self.assertIn("retry", [event.event for event in events])
        self.assertEqual(executor.calls[0]["arguments"]["query"], "old")
        self.assertEqual(executor.calls[1]["arguments"]["query"], "new")

    async def test_run_to_result_collects_artifacts_and_trace_summary(self) -> None:
        artifact = AgentArtifactRef(artifact_id="md1", kind="markdown", url="/media/md1.md")
        planner = SequencePlanner(
            [
                AgentDecision.tool(name="web_search_knowledge", arguments={"topic": "函数"}, step_id="s1"),
                AgentDecision.finish(summary="完成"),
            ]
        )
        executor = RecordingToolExecutor([ToolResult(success=True, output={"artifacts": [artifact.to_dict()]})])
        runtime = AgentRuntime(planner=planner, tool_executor=executor)

        result = await runtime.run_to_result(make_spec())

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.artifacts[0].artifact_id, "md1")
        self.assertEqual(result.trace_summary["tool_calls"], 1)

    async def test_cancelled_tool_returns_cancelled_result(self) -> None:
        planner = SequencePlanner([AgentDecision.tool(name="web_search_knowledge", arguments={}, step_id="s1")])
        runtime = AgentRuntime(planner=planner, tool_executor=CancelingToolExecutor())

        result = await runtime.run_to_result(make_spec())

        self.assertEqual(result.status, "canceled")
        self.assertEqual(result.error, "agent_run_canceled")


if __name__ == "__main__":
    unittest.main()
