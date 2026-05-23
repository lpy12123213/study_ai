from __future__ import annotations

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
        from backend.generation.question_library import runner as ql_runner

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
