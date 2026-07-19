from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.generation.agentic.task_specs import build_agent_run_spec_for_task
from backend.shared.tasks.runtime import RuntimeTask


def _task(task_type: str, request: dict) -> RuntimeTask:
    spec = build_agent_run_spec_for_task(task_type=task_type, request=request)
    return RuntimeTask(
        task_id=f"{task_type}-1",
        user_id="u-1",
        task_type=task_type,
        title=task_type,
        request=dict(request),
        meta={"agent_run_spec": spec.to_dict() if spec is not None else {}},
    )


class CodexRuntimeTaskWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_task_runners_delegate_to_codex_runtime(self) -> None:
        from backend.tasks import runners

        cases = [
            (runners.run_deepthink_task, _task("deepthink", {"question": "x^2", "subject": "高中数学"})),
            (
                runners.run_lesson_plan_task,
                _task("lesson_plan", {"subject": "高中数学", "grade": "高一", "topic": "函数"}),
            ),
            (
                runners.run_knowledge_video_task,
                _task("knowledge_video", {"subject": "高中数学", "topic": "函数"}),
            ),
        ]

        for fn, task in cases:
            with self.subTest(task_type=task.task_type), patch.object(
                runners,
                "run_codex_runtime_task",
                new=AsyncMock(return_value=True),
            ) as codex_run:
                await fn(task, user_id="u-1")

            codex_run.assert_awaited_once()

    async def test_question_evaluate_runner_delegates_to_codex_runtime(self) -> None:
        from backend.generation.question_evaluate import runner

        task = _task(
            "question_evaluate",
            {"subject": "高中数学", "questions": [{"question_id": "q1", "stem": "已知 f(x)=x^2。"}]},
        )

        with patch.object(runner, "run_codex_runtime_task", new=AsyncMock(return_value=True)) as codex_run, patch.object(
            runner,
            "evaluate_questions_batch",
            side_effect=AssertionError("legacy evaluator should not run"),
        ):
            await runner.run_question_evaluate_task(task, user_id="u-1")

        codex_run.assert_awaited_once()

    async def test_question_library_score_uses_codex_but_generate_uses_domain_pipeline(self) -> None:
        from backend.generation.question_library import runner as ql_runner

        created: list[RuntimeTask] = []

        async def fake_create_task(**kwargs):
            task = RuntimeTask(
                task_id=kwargs["task_id"],
                user_id=kwargs["user_id"],
                task_type=kwargs["task_type"],
                title=kwargs["title"],
                request=kwargs["request"],
                meta=kwargs.get("meta") or {},
            )
            created.append(task)
            await kwargs["runner_factory"](task)
            return task

        with patch.object(ql_runner, "is_llm_configured", return_value=True), patch.object(
            ql_runner.task_runtime,
            "create_task",
            new=AsyncMock(side_effect=fake_create_task),
        ), patch.object(
            ql_runner,
            "save_session",
            side_effect=lambda value: value,
        ), patch.object(
            ql_runner,
            "load_session",
            return_value=None,
        ), patch.object(
            ql_runner,
            "new_session_id",
            return_value="session-1",
        ), patch.object(
            ql_runner,
            "new_preview_id",
            return_value="preview-1",
        ), patch.object(
            ql_runner,
            "save_preview",
            side_effect=lambda value: value,
        ), patch.object(
            ql_runner,
            "build_source_pack",
            new=AsyncMock(
                return_value={
                    "subject": "高中数学",
                    "topic": "函数",
                    "skills": ["函数"],
                    "question_requirements": ["课内"],
                }
            ),
        ), patch.object(
            ql_runner,
            "build_curriculum_context",
            new=AsyncMock(return_value={"question_requirements": ["课内"], "knowledge_scope": {"in_scope": ["函数"]}}),
        ), patch.object(
            ql_runner,
            "generate_questions",
            new=AsyncMock(return_value=[]),
        ) as domain_generate, patch.object(
            ql_runner,
            "collect_reference_questions",
            new=AsyncMock(return_value={"questions": []}),
        ), patch.object(
            ql_runner,
            "run_codex_runtime_task",
            new=AsyncMock(return_value=True),
        ) as codex_run:
            await ql_runner.create_score_task(user_id="u-1", request={"subject": "高中数学", "limit": 2})
            await ql_runner.create_generate_task(
                user_id="u-1",
                request={"subject": "高中数学", "topic": "函数", "question_type": "解答题", "count": 1},
            )

        self.assertEqual([task.task_type for task in created], ["question_library_score", "question_library_generate"])
        self.assertEqual(codex_run.await_count, 1)
        domain_generate.assert_awaited_once()

    async def test_question_library_score_runner_falls_back_when_codex_returns_false(self) -> None:
        """If codex runtime signals it did not handle the task and fallback is on, legacy path must run."""

        from backend.generation.question_library import runner as ql_runner

        class _LegacyPathReached(Exception):
            pass

        legacy_called = False

        async def append_event_marker(_task, _event):
            nonlocal legacy_called
            legacy_called = True
            raise _LegacyPathReached()

        async def fake_create_task(**kwargs):
            task = RuntimeTask(
                task_id=kwargs["task_id"],
                user_id=kwargs["user_id"],
                task_type=kwargs["task_type"],
                title=kwargs["title"],
                request=kwargs["request"],
                meta=kwargs.get("meta") or {},
            )
            try:
                await kwargs["runner_factory"](task)
            except _LegacyPathReached:
                pass
            return task

        with patch.object(ql_runner, "is_llm_configured", return_value=True), patch.object(
            ql_runner.task_runtime,
            "create_task",
            new=AsyncMock(side_effect=fake_create_task),
        ), patch.object(
            ql_runner.task_runtime,
            "append_event",
            new=AsyncMock(side_effect=append_event_marker),
        ), patch.object(
            ql_runner.task_runtime,
            "fail_task",
            new=AsyncMock(),
        ), patch.object(
            ql_runner,
            "is_codex_runtime_agent_runtime",
            return_value=True,
        ), patch.object(
            ql_runner,
            "legacy_agent_fallback_enabled",
            return_value=True,
        ), patch.object(
            ql_runner,
            "run_codex_runtime_task",
            new=AsyncMock(return_value=False),
        ) as codex_run:
            await ql_runner.create_score_task(user_id="u-1", request={"subject": "高中数学", "limit": 2})

        codex_run.assert_awaited_once()
        self.assertTrue(legacy_called, "legacy path must run when codex returns False and fallback is enabled")


if __name__ == "__main__":
    unittest.main()
