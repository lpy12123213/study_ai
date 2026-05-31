from __future__ import annotations

import os
import unittest
from unittest.mock import patch


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

        with patch.dict(os.environ, {"PAPER_COMPOSE_AGENTIC_FULL": "0"}, clear=False), patch.object(
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


if __name__ == "__main__":
    unittest.main()
