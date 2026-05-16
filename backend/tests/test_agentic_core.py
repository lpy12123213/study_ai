from __future__ import annotations

# ruff: noqa: E402,I001

# ---- from backend/tests/test_agentic_task_specs.py ----
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class AgenticTaskSpecTests(unittest.TestCase):
    def test_medium_and_heavy_ai_task_types_have_native_agent_specs(self) -> None:
        from backend.generation.agentic.task_specs import build_agent_run_spec_for_task

        cases = {
            "deepthink": {"question": "已知函数 f(x)=x^2，求单调区间", "subject": "高中数学"},
            "lesson_plan": {"subject": "高中数学", "grade": "高一", "topic": "函数单调性"},
            "paper_compose": {"subject": "高中数学", "paperName": "函数测试卷", "blueprint": []},
            "paper_generate_full": {"subject": "高中数学", "topic": "函数", "count": 12},
            "knowledge_video": {"topic": "函数单调性", "subject": "高中数学"},
            "question_library_generate": {
                "subject": "高中数学",
                "topic": "函数单调性",
                "question_type": "解答题",
                "count": 3,
            },
            "question_library_score": {"subject": "高中数学", "limit": 30, "only_unscored": True},
            "question_evaluate": {
                "subject": "高中数学",
                "questions": [{"question_id": "q1", "stem": "已知 f(x)=x^2，判断单调性。"}],
            },
        }

        for task_type, request in cases.items():
            with self.subTest(task_type=task_type):
                spec = build_agent_run_spec_for_task(task_type=task_type, request=request)

                self.assertIsNotNone(spec)
                self.assertTrue(spec.goal.strip())
                self.assertTrue(spec.roles)
                self.assertGreater(spec.budget.max_iterations, 1)
                self.assertTrue(spec.tool_policy.allowed_tools)
                self.assertEqual(spec.metadata.get("native_agentic"), True)

    def test_agentic_starter_event_preserves_task_step_shape_and_embeds_spec(self) -> None:
        from backend.generation.agentic.task_specs import build_agent_run_spec_for_task, build_agentic_starter_event

        spec = build_agent_run_spec_for_task(
            task_type="deepthink",
            request={"question": "证明三角形内角和", "subject": "初中数学"},
        )
        event = build_agentic_starter_event(spec=spec, title="开始深度解题", tool_name="deepthink")

        self.assertEqual(event["type"], "step")
        self.assertEqual(event["step"]["id"], "agent_run_started")
        self.assertEqual(event["step"]["status"], "running")
        self.assertEqual(event["data"]["native_agentic"], True)
        self.assertEqual(event["data"]["agent_run_spec"]["domain"], "deepthink")


class AgenticTaskSubmitTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_ai_task_submitters_attach_agent_spec_metadata(self) -> None:
        from backend.tasks import submit as submitters

        async def fake_create_task(**kwargs):
            return SimpleNamespace(
                task_id=kwargs["task_id"],
                user_id=kwargs["user_id"],
                task_type=kwargs["task_type"],
                request=kwargs["request"],
                meta=kwargs.get("meta") or {},
                starter_event=kwargs.get("starter_event") or {},
                status="running",
            )

        cases = [
            (
                submitters.submit_deepthink_task,
                {"question": "已知函数 f(x)=x^2，求单调区间", "subject": "高中数学"},
                "deepthink",
            ),
            (
                submitters.submit_lesson_plan_task,
                {"subject": "高中数学", "grade": "高一", "topic": "函数单调性"},
                "lesson_plan",
            ),
            (
                submitters.submit_paper_compose_task,
                {"subject": "高中数学", "paperName": "函数测试卷", "blueprint": []},
                "paper_compose",
            ),
            (
                submitters.submit_generate_full_paper_task,
                {"subject": "高中数学", "topic": "函数", "count": 12},
                "paper_generate_full",
            ),
            (
                submitters.submit_knowledge_video_task,
                {"topic": "函数单调性", "subject": "高中数学"},
                "knowledge_video",
            ),
            (
                submitters.submit_question_evaluate_task,
                {
                    "subject": "高中数学",
                    "questions": [{"question_id": "q1", "stem": "已知 f(x)=x^2，判断单调性。"}],
                },
                "question_evaluate",
            ),
        ]

        with patch.object(submitters.task_runtime, "create_task", new=AsyncMock(side_effect=fake_create_task)):
            for fn, request, task_type in cases:
                with self.subTest(task_type=task_type):
                    task = await fn(user_id="u-1", request=request)

                    spec = task.meta.get("agent_run_spec")
                    self.assertIsInstance(spec, dict)
                    self.assertEqual(spec.get("metadata", {}).get("native_agentic"), True)
                    self.assertEqual(task.starter_event.get("data", {}).get("native_agentic"), True)
                    self.assertEqual(task.starter_event.get("step", {}).get("id"), "agent_run_started")

    async def test_question_library_ai_task_submitters_attach_agent_spec_metadata(self) -> None:
        from backend.question_library import runner as ql_runner

        async def fake_create_task(**kwargs):
            return SimpleNamespace(
                task_id=kwargs["task_id"],
                user_id=kwargs["user_id"],
                task_type=kwargs["task_type"],
                request=kwargs["request"],
                meta=kwargs.get("meta") or {},
                starter_event=kwargs.get("starter_event") or {},
                status="running",
            )

        with patch.object(ql_runner, "is_llm_configured", return_value=True), patch.object(
            ql_runner.task_runtime,
            "create_task",
            new=AsyncMock(side_effect=fake_create_task),
        ), patch.object(ql_runner, "save_session"), patch.object(ql_runner, "load_session", return_value=None), patch.object(
            ql_runner,
            "new_session_id",
            return_value="session-1",
        ), patch.object(ql_runner, "new_preview_id", return_value="preview-1"):
            score_task = await ql_runner.create_score_task(
                user_id="u-1",
                request={"subject": "高中数学", "limit": 10, "task_id": "score-1"},
            )
            generate_task = await ql_runner.create_generate_task(
                user_id="u-1",
                request={
                    "subject": "高中数学",
                    "topic": "函数单调性",
                    "question_type": "解答题",
                    "count": 2,
                    "task_id": "gen-1",
                },
            )

        for task in [score_task, generate_task]:
            with self.subTest(task_type=task.task_type):
                spec = task.meta.get("agent_run_spec")
                self.assertIsInstance(spec, dict)
                self.assertEqual(spec.get("metadata", {}).get("native_agentic"), True)
                self.assertEqual(task.starter_event.get("data", {}).get("native_agentic"), True)
                self.assertEqual(task.starter_event.get("step", {}).get("id"), "agent_run_started")


if __name__ == "__main__":
    unittest.main()


# ---- from backend/tests/test_agentic_types.py ----


import unittest

from backend.generation.agentic.types import (
    AgentArtifactRef,
    AgentBudget,
    AgentRoleSpec,
    AgentRunResult,
    AgentRunSpec,
    AgentSearchPolicy,
    AgentToolPolicy,
    AgentTraceEvent,
)


class AgenticTypesTests(unittest.TestCase):
    def test_agent_run_spec_round_trips_to_dict(self) -> None:
        spec = AgentRunSpec(
            domain="study_materials",
            goal="生成函数单调性自学资料",
            subject="高中数学",
            user_requirements="偏直观",
            input_payload={"topic": "函数单调性"},
            roles=[
                AgentRoleSpec(name="planner", prompt_id="agent.planner.study_materials.v1"),
                AgentRoleSpec(name="writer", prompt_id="study.material.writer.v1"),
            ],
            tool_policy=AgentToolPolicy(allowed_tools=["web_search_knowledge", "generate_study_material"]),
            search_policy=AgentSearchPolicy(),
            budget=AgentBudget(max_llm_calls=8, max_tool_calls=12, max_iterations=5),
            output_contract={"kind": "markdown"},
            resume_state={"last_stage": "search"},
        )

        data = spec.to_dict()
        restored = AgentRunSpec.from_dict(data)

        self.assertEqual(restored.domain, "study_materials")
        self.assertEqual(restored.input_payload["topic"], "函数单调性")
        self.assertEqual(restored.roles[0].name, "planner")
        self.assertEqual(restored.tool_policy.allowed_tools, ["web_search_knowledge", "generate_study_material"])
        self.assertEqual(restored.search_policy.providers[0], "tavily")
        self.assertEqual(restored.budget.max_llm_calls, 8)

    def test_trace_event_maps_to_task_event_shape(self) -> None:
        event = AgentTraceEvent(
            event="tool_call",
            role="researcher",
            step_id="s1",
            data={"name": "web_search_knowledge", "arguments": {"topic": "函数"}},
        )

        task_event = event.to_task_event(seq=3)

        self.assertEqual(task_event["seq"], 3)
        self.assertEqual(task_event["event"], "tool_call")
        self.assertEqual(task_event["data"]["role"], "researcher")
        self.assertEqual(task_event["data"]["step_id"], "s1")
        self.assertEqual(task_event["data"]["name"], "web_search_knowledge")

    def test_run_result_round_trips_artifacts(self) -> None:
        result = AgentRunResult(
            status="completed",
            summary="完成",
            artifacts=[
                AgentArtifactRef(
                    artifact_id="a1",
                    kind="markdown",
                    title="资料",
                    url="/media/a1.md",
                    metadata={"chars": 1200},
                )
            ],
            trace_summary={"tool_calls": 3},
        )

        restored = AgentRunResult.from_dict(result.to_dict())

        self.assertEqual(restored.status, "completed")
        self.assertEqual(restored.artifacts[0].kind, "markdown")
        self.assertEqual(restored.trace_summary["tool_calls"], 3)


if __name__ == "__main__":
    unittest.main()


# ---- from backend/tests/test_agentic_task_adapter.py ----


import unittest

from backend.generation.agentic.task_adapter import (
    agent_trace_to_task_event,
    progress_from_agent_event,
)


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


# ---- from backend/tests/test_agentic_runtime.py ----


import asyncio
import unittest
from typing import Any, Dict, List

from backend.generation.agentic.runtime import AgentRuntime
from backend.generation.agentic.tooling import AgentDecision, ToolResult


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
