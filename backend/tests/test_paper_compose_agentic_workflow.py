from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch


class PaperComposeAgenticWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_full_paper_uses_agentic_runner_by_default(self) -> None:
        from backend.generation.paper_compose import full_paper_workflow

        async def fake_agentic_events(*_args, **_kwargs):
            yield {"type": "agent_decision", "data": {"name": "generate_questions_ai"}}
            yield {"type": "result", "result": {"paper_id": 12, "paper_name": "agentic"}}

        with patch.dict(os.environ, {}, clear=True), patch.object(
            full_paper_workflow,
            "run_agentic_full_paper_events",
            side_effect=fake_agentic_events,
        ) as agentic_run, patch.object(
            full_paper_workflow,
            "plan_exam_structure",
            side_effect=AssertionError("legacy planner should not run"),
        ):
            events = [
                event
                async for event in full_paper_workflow.generate_full_paper_events(
                    {"subject": "高中数学", "topic": "函数", "paperName": "测试卷"},
                    user_id="u-1",
                )
            ]

        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["result"]["paper_id"], 12)
        agentic_run.assert_called_once()

    async def test_generate_full_paper_can_use_legacy_runner_for_rollback(self) -> None:
        from backend.generation.paper_compose import full_paper_workflow

        with patch.dict(os.environ, {"AGENT_RUNTIME": "legacy", "PAPER_COMPOSE_AGENTIC_FULL": "0"}, clear=False), patch.object(
            full_paper_workflow,
            "run_agentic_full_paper_events",
            side_effect=AssertionError("agentic runner should not run"),
        ), patch.object(
            full_paper_workflow,
            "resolve_subject",
            return_value="高中数学",
        ), patch.object(
            full_paper_workflow,
            "plan_exam_structure",
            return_value={"slots": []},
        ) as legacy_planner:
            events = [
                event
                async for event in full_paper_workflow.generate_full_paper_events(
                    {"subject": "高中数学", "topic": "函数", "paperName": "测试卷"},
                    user_id="u-1",
                )
            ]

        self.assertTrue(any(event.get("error") == "plan_structure_failed" for event in events))
        legacy_planner.assert_called_once()

    async def test_paper_compose_planner_uses_llm_decision_when_configured(self) -> None:
        from backend.generation.agentic.task_specs import build_agent_run_spec_for_task
        from backend.generation.paper_compose import agentic_workflow
        from backend.llm.prompts import create_default_prompt_registry

        spec = build_agent_run_spec_for_task(
            task_type="paper_generate_full",
            request={"subject": "高中数学", "topic": "函数", "paperName": "测试卷"},
        )
        planner = agentic_workflow.PaperComposePlanner()

        with patch.object(agentic_workflow, "is_llm_configured", return_value=True), patch.object(
            agentic_workflow,
            "chat_completion_text",
            return_value='{"action":"tool","tool_name":"generate_questions_ai","role":"author","step_id":"author_questions","arguments":{"count":2},"thought":"题库不足，先原创。"}',
        ) as llm_call:
            decision = await planner.next_decision(spec=spec, state={"tool_outputs": {}})

        self.assertEqual(decision.action, "tool")
        self.assertEqual(decision.tool_name, "generate_questions_ai")
        self.assertEqual(decision.role, "author")
        self.assertEqual(decision.step_id, "author_questions")
        self.assertEqual(decision.arguments["count"], 2)
        llm_call.assert_called_once()
        self.assertEqual(
            llm_call.call_args.kwargs["messages"][0]["content"],
            create_default_prompt_registry().render("paper_compose.planner.v1").content,
        )

    async def test_agentic_paper_compose_uses_codex_runtime(self) -> None:
        from backend.generation.paper_compose import agentic_workflow

        async def fake_codex_events(*_args, **_kwargs):
            yield {"type": "progress", "progress": 3.0, "stage": "codex_runtime_start"}
            yield {"type": "result", "result": {"paper_id": 31, "paper_name": "codex-runtime"}}

        with patch.object(
            agentic_workflow,
            "run_codex_runtime_agent_events",
            side_effect=fake_codex_events,
            create=True,
        ) as codex_run, patch.object(
            agentic_workflow,
            "PaperComposePlanner",
            side_effect=AssertionError("legacy PaperComposePlanner should not run"),
        ):
            events = [
                event
                async for event in agentic_workflow.run_agentic_blueprint_paper_events(
                    {"subject": "高中数学", "paperName": "测试卷"},
                    user_id="u-1",
                )
            ]

        codex_run.assert_called_once()
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["result"]["paper_id"], 31)

    async def test_paper_compose_runner_uses_codex_runtime_agentic_blueprint_by_default(self) -> None:
        from backend.shared.tasks import RuntimeTask
        from backend.tasks import runners

        async def fake_agentic_events(*_args, **_kwargs):
            yield {"type": "result", "result": {"paper_id": 21, "paper_name": "codex-runtime"}}

        task = RuntimeTask(
            task_id="compose-codex",
            user_id="u-1",
            task_type="paper_compose",
            title="codex",
            request={"subject": "高中数学", "paperName": "测试卷"},
        )

        with patch.dict(os.environ, {}, clear=True), patch.object(
            runners,
            "run_agentic_blueprint_paper_events",
            side_effect=fake_agentic_events,
        ) as agentic_run, patch.object(
            runners,
            "compose_paper_events",
            side_effect=AssertionError("legacy blueprint should not run by default"),
        ), patch.object(
            runners.task_runtime,
            "append_event",
            new=AsyncMock(),
        ), patch.object(
            runners.task_runtime,
            "complete_task",
            new=AsyncMock(),
        ) as complete:
            await runners.run_paper_compose_task(task, user_id="u-1")

        agentic_run.assert_called_once()
        complete.assert_awaited_once()
        self.assertEqual(complete.await_args.kwargs["result"]["paper_id"], 21)

    async def test_paper_compose_runner_defers_codex_pending_review_draft(self) -> None:
        from backend.shared.tasks import RuntimeTask
        from backend.tasks import runners

        draft = {
            "paperName": "待审卷",
            "subject": "高中数学",
            "questions": [{"question_id": "q-codex", "stem": "Codex 待审题"}],
        }

        async def fake_agentic_events(*_args, **_kwargs):
            yield {"type": "progress", "progress": 3.0, "stage": "codex_runtime_start"}
            yield {"type": "pending_review", "taskId": "compose-codex-review", "composeDraft": draft}

        async def fake_defer(target_task, **_kwargs):
            target_task.status = "pending_review"

        task = RuntimeTask(
            task_id="compose-codex-review",
            user_id="u-1",
            task_type="paper_compose",
            title="codex-review",
            request={"subject": "高中数学", "paperName": "待审卷"},
        )

        with patch.dict(os.environ, {}, clear=True), patch.object(
            runners,
            "run_agentic_blueprint_paper_events",
            side_effect=fake_agentic_events,
        ) as agentic_run, patch.object(
            runners,
            "compose_paper_events",
            side_effect=AssertionError("legacy compose should not run for codex pending_review"),
        ), patch.object(
            runners.task_runtime,
            "append_event",
            new=AsyncMock(),
        ) as append_event, patch.object(
            runners.task_runtime,
            "defer_task",
            new=AsyncMock(side_effect=fake_defer),
        ) as defer, patch.object(
            runners.task_runtime,
            "complete_task",
            new=AsyncMock(),
        ) as complete, patch.object(
            runners.task_runtime,
            "fail_task",
            new=AsyncMock(),
        ) as fail:
            await runners.run_paper_compose_task(task, user_id="u-1")

        agentic_run.assert_called_once()
        self.assertEqual(append_event.await_count, 2)
        defer.assert_awaited_once_with(task, status="pending_review", result={"composeDraft": draft})
        complete.assert_not_awaited()
        fail.assert_not_awaited()

    async def test_codex_pending_review_after_recoverable_error_does_not_fall_back_to_legacy(self) -> None:
        from backend.generation.paper_compose import agentic_workflow

        draft = {
            "paperName": "待审卷",
            "subject": "高中数学",
            "questions": [{"question_id": "q-codex", "stem": "恢复后待审题"}],
        }

        async def fake_codex_events(**_kwargs):
            yield {"type": "error", "data": {"code": "recoverable_tool_error"}}
            yield {"type": "pending_review", "taskId": "compose-codex-review", "composeDraft": draft}

        with patch.object(
            agentic_workflow,
            "is_codex_runtime_agent_runtime",
            return_value=True,
        ), patch.object(
            agentic_workflow,
            "legacy_agent_fallback_enabled",
            return_value=True,
        ), patch.object(
            agentic_workflow,
            "run_codex_runtime_agent_events",
            side_effect=fake_codex_events,
        ), patch.object(
            agentic_workflow.AgentRuntime,
            "run",
            side_effect=AssertionError("legacy runtime must not run after codex pending_review"),
        ):
            events = [
                event
                async for event in agentic_workflow.run_agentic_blueprint_paper_events(
                    {"taskId": "compose-codex-review", "subject": "高中数学"},
                    user_id="u-1",
                )
            ]

        self.assertEqual(events, [{"type": "pending_review", "taskId": "compose-codex-review", "composeDraft": draft}])

    async def test_agentic_paper_compose_does_not_fall_back_after_terminal_codex_error(self) -> None:
        from backend.generation.paper_compose import agentic_workflow

        async def failing_codex_events(*_args, **_kwargs):
            yield {"type": "error", "data": {"code": "codex_runtime_failed"}}

        with patch.object(
            agentic_workflow,
            "is_codex_runtime_agent_runtime",
            return_value=True,
        ), patch.object(
            agentic_workflow,
            "legacy_agent_fallback_enabled",
            return_value=True,
        ), patch.object(
            agentic_workflow,
            "run_codex_runtime_agent_events",
            side_effect=failing_codex_events,
        ) as codex_run, patch.object(
            agentic_workflow.AgentRuntime,
            "run",
            side_effect=AssertionError("legacy runtime must not run after an explicit codex error"),
        ):
            events = [
                event
                async for event in agentic_workflow.run_agentic_blueprint_paper_events(
                    {"subject": "高中数学", "paperName": "测试卷"},
                    user_id="u-1",
                )
            ]

        codex_run.assert_called_once()
        self.assertEqual(events, [{"type": "error", "data": {"code": "codex_runtime_failed"}}])

    async def test_agentic_paper_compose_only_falls_back_after_nonterminal_stream_exhaustion(self) -> None:
        from backend.generation.agentic.types import AgentTraceEvent
        from backend.generation.paper_compose import agentic_workflow

        async def exhausted_codex_events(*_args, **_kwargs):
            yield {"type": "status", "data": {"content": "Codex runtime started"}}

        async def legacy_runtime_events(self, _spec):  # noqa: ARG001
            yield AgentTraceEvent(event="finish", data={})

        with patch.object(
            agentic_workflow,
            "is_codex_runtime_agent_runtime",
            return_value=True,
        ), patch.object(
            agentic_workflow,
            "legacy_agent_fallback_enabled",
            return_value=True,
        ), patch.object(
            agentic_workflow,
            "run_codex_runtime_agent_events",
            side_effect=exhausted_codex_events,
        ), patch.object(
            agentic_workflow.AgentRuntime,
            "run",
            new=legacy_runtime_events,
        ), patch.object(
            agentic_workflow,
            "_result_from_context",
            return_value={"paper_id": 99, "paper_name": "legacy-fallback"},
        ):
            events = [
                event
                async for event in agentic_workflow.run_agentic_blueprint_paper_events(
                    {"subject": "高中数学", "paperName": "测试卷"},
                    user_id="u-1",
                )
            ]

        self.assertEqual(events[0]["type"], "status")
        self.assertTrue(any(event.get("stage") == "codex_runtime_fallback" for event in events))
        self.assertEqual(events[-1]["result"]["paper_id"], 99)

    async def test_agentic_paper_compose_propagates_error_when_no_fallback(self) -> None:
        """Without ``CODEX_RUNTIME_FALLBACK_LEGACY`` enabled, codex errors must
        bubble up so the task fails fast instead of silently switching runtime."""

        from backend.generation.paper_compose import agentic_workflow

        async def failing_codex_events(*_args, **_kwargs):
            yield {"type": "error", "data": {"code": "codex_runtime_failed"}}

        with patch.object(
            agentic_workflow,
            "is_codex_runtime_agent_runtime",
            return_value=True,
        ), patch.object(
            agentic_workflow,
            "legacy_agent_fallback_enabled",
            return_value=False,
        ), patch.object(
            agentic_workflow,
            "run_codex_runtime_agent_events",
            side_effect=failing_codex_events,
        ), patch.object(
            agentic_workflow,
            "PaperComposePlanner",
            side_effect=AssertionError("legacy must not run when fallback is disabled"),
        ):
            events = [
                event
                async for event in agentic_workflow.run_agentic_blueprint_paper_events(
                    {"subject": "高中数学", "paperName": "测试卷"},
                    user_id="u-1",
                )
            ]

        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["data"]["code"], "codex_runtime_failed")

    async def test_paper_compose_runner_uses_agentic_blueprint_when_enabled(self) -> None:
        from backend.shared.tasks import RuntimeTask
        from backend.tasks import runners

        async def fake_agentic_events(*_args, **_kwargs):
            yield {"type": "agent_decision", "data": {"name": "compose_paper_blueprint"}}
            yield {"type": "result", "result": {"paper_id": 22, "paper_name": "agentic-blueprint"}}

        task = RuntimeTask(
            task_id="compose-agentic",
            user_id="u-1",
            task_type="paper_compose",
            title="agentic",
            request={"subject": "高中数学", "paperName": "测试卷"},
        )

        with patch.dict(os.environ, {"PAPER_COMPOSE_AGENTIC_BLUEPRINT": "1"}, clear=False), patch.object(
            runners,
            "run_agentic_blueprint_paper_events",
            side_effect=fake_agentic_events,
        ) as agentic_run, patch.object(
            runners,
            "compose_paper_events",
            side_effect=AssertionError("legacy blueprint should not run"),
        ), patch.object(
            runners.task_runtime,
            "append_event",
            new=AsyncMock(),
        ), patch.object(
            runners.task_runtime,
            "complete_task",
            new=AsyncMock(),
        ) as complete:
            await runners.run_paper_compose_task(task, user_id="u-1")

        agentic_run.assert_called_once()
        complete.assert_awaited_once()
        self.assertEqual(complete.await_args.kwargs["result"]["paper_id"], 22)


if __name__ == "__main__":
    unittest.main()
