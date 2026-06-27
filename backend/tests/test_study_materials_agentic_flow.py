from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.generation.agentic.study_materials import build_study_materials_agent_spec
from backend.generation.study_materials.orchestrator import StudyMaterialsTaskManager
from backend.generation.study_materials.quality_gate import (
    QUALITY_POLICY_VERSION,
    REVIEW_SCHEMA_VERSION,
    draft_hash,
)
from backend.llm.prompts import create_default_prompt_registry


def _task(*, task_id: str = "study-1", options: dict | None = None, meta: dict | None = None):
    return SimpleNamespace(
        task_id=task_id,
        user_id="u-1",
        request={
            "query": "函数单调性",
            "subject": "高中数学",
            "options": dict(options or {"preset": "standard"}),
        },
        meta=dict(meta or {}),
        parent_task_id=None,
        status="running",
        task_type="study_materials",
    )


def _accepted_result(markdown: str = "# 函数单调性\n\n## 增函数\n\n定义、性质、条件、反例和例题。") -> dict:
    acceptance = {
        "accepted": True,
        "preset": "standard",
        "draft_hash": draft_hash(markdown),
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "failed_checks": [],
    }
    workflow = {
        "version": 1,
        "stage": "completed",
        "preset": "standard",
        "markdown": markdown,
        "acceptance": acceptance,
    }
    resume = {
        "markdown": markdown,
        "assemble_study_archive": markdown,
        "study_materials_workflow": workflow,
        "step_results": [{"step_id": "review-1", "tool": "review_content", "success": True}],
    }
    return {
        "success": True,
        "material": {
            "topic": "函数单调性",
            "subject": "高中数学",
            "markdown": markdown,
            "iteration": 1,
            "passed": True,
            "issues": [],
            "error": None,
        },
        "acceptance": acceptance,
        "quality_report": {"passed": True, "failed_checks": []},
        "workflow": workflow,
        "resume_working_memory": resume,
    }


class StudyMaterialsAgenticFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_study_materials_agent_spec_defaults_to_tavily_search_policy(self) -> None:
        spec = build_study_materials_agent_spec(
            query="函数单调性",
            subject="高中数学",
            options={"preset": "deep", "requirements": "偏直观"},
        )

        self.assertEqual(spec.domain, "study_materials")
        self.assertIn("函数单调性", spec.goal)
        self.assertEqual(spec.subject, "高中数学")
        self.assertEqual(spec.user_requirements, "偏直观")
        self.assertEqual(spec.search_policy.providers[0], "tavily")
        self.assertIn("web_search_knowledge", spec.tool_policy.allowed_tools)
        self.assertNotIn("compile_latex_to_pdf", spec.tool_policy.allowed_tools)
        self.assertEqual(spec.output_contract.get("formats"), ["markdown"])
        self.assertEqual(spec.output_contract.get("deferred_formats"), ["latex", "pdf"])
        self.assertTrue(any(role.name == "planner" for role in spec.roles))
        self.assertTrue(any(role.name == "writer" for role in spec.roles))

        registry = create_default_prompt_registry()
        for role in spec.roles:
            with self.subTest(role=role.name):
                self.assertIsNotNone(registry.get(role.prompt_id))

    async def test_create_task_persists_agent_run_spec_in_meta(self) -> None:
        manager = StudyMaterialsTaskManager()

        async def fake_create_task(**kwargs):
            return SimpleNamespace(
                task_id=kwargs["task_id"],
                user_id=kwargs["user_id"],
                request=kwargs["request"],
                meta=kwargs["meta"],
                parent_task_id=kwargs.get("parent_task_id"),
                status="running",
                created_at_s=1.0,
                updated_at_s=1.0,
            )

        with patch(
            "backend.generation.study_materials.orchestrator.task_runtime.create_task",
            new=AsyncMock(side_effect=fake_create_task),
        ), patch.object(manager, "_persist_snapshot"):
            task = await manager.create_task(
                query="函数单调性",
                user_id="u-1",
                subject="高中数学",
                options={"preset": "standard"},
            )

        spec = task.meta.get("agent_run_spec")
        self.assertIsInstance(spec, dict)
        self.assertEqual(spec["domain"], "study_materials")
        self.assertEqual(spec["input_payload"]["topic"], "函数单调性")
        self.assertEqual(spec["search_policy"]["providers"][0], "tavily")
        self.assertEqual(spec["metadata"]["runtime"], "codex_runtime")

    async def test_run_task_completes_only_from_accepted_workflow_result(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task(meta={"agent_run_spec": build_study_materials_agent_spec(query="函数单调性").to_dict()})
        accepted = _accepted_result()

        async def fake_workflow(**kwargs):
            await kwargs["event_sink"](
                {"type": "workflow_stage", "event": "workflow_stage", "data": {"stage": "review"}}
            )
            await kwargs["checkpoint_sink"](accepted["workflow"], accepted["resume_working_memory"])
            return accepted

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.object(orchestrator, "AgentCore", side_effect=AssertionError("legacy AgentCore should not run")), patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(side_effect=fake_workflow),
            create=True,
        ) as run_workflow, patch.object(
            orchestrator,
            "upsert_study_archive",
            new=AsyncMock(),
        ) as upsert, patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ) as append_event, patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        run_workflow.assert_awaited_once()
        complete.assert_awaited_once()
        upsert.assert_awaited_once()
        self.assertEqual(upsert.await_args.kwargs["acceptance"], accepted["acceptance"])
        self.assertEqual(task.meta["study_materials_workflow"]["stage"], "completed")
        self.assertTrue(any(call.args[1].get("type") == "workflow_stage" for call in append_event.await_args_list))

    async def test_quality_gate_failure_is_recoverable_and_never_completes(self) -> None:
        from backend.generation.study_materials import orchestrator
        from backend.generation.study_materials.workflow import WorkflowFailure

        manager = StudyMaterialsTaskManager()
        task = _task(task_id="study-fail")
        failure = WorkflowFailure(
            "quality_gate_not_met",
            stage="review",
            issues=["independent_review_failed"],
            recoverable=True,
        )

        async def fake_fail(runtime_task, *_args, **_kwargs):
            runtime_task.status = "failed"

        with patch.object(orchestrator, "AgentCore", side_effect=AssertionError("legacy AgentCore should not run")), patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(side_effect=failure),
            create=True,
        ), patch.object(orchestrator.task_runtime, "append_event", new=AsyncMock()), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(),
        ) as complete, patch.object(
            orchestrator.task_runtime,
            "fail_task",
            new=AsyncMock(side_effect=fake_fail),
        ) as fail, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        complete.assert_not_awaited()
        fail.assert_awaited_once()
        self.assertEqual(fail.await_args.kwargs["error"]["code"], "quality_gate_not_met")
        self.assertTrue(fail.await_args.kwargs["error"]["recoverable"])

    async def test_current_accepted_local_archive_keeps_fast_path(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task(options={"preset": "standard"})
        markdown = _accepted_result()["material"]["markdown"]
        archive = {
            "markdown": markdown,
            "sections": [],
            "acceptance": _accepted_result()["acceptance"],
        }

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=archive),
        ), patch.object(
            orchestrator,
            "_export_markdown_to_media",
            new=AsyncMock(return_value={"md_url": "/m.md", "md_filename": "m.md"}),
        ), patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(),
            create=True,
        ) as run_workflow, patch.object(orchestrator.task_runtime, "append_event", new=AsyncMock()), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        run_workflow.assert_not_awaited()
        complete.assert_awaited_once()
        self.assertTrue(complete.await_args.kwargs["result"]["reused_local_archive"])

    async def test_stale_local_archive_is_a_candidate_not_an_automatic_success(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task(options={"preset": "standard"})
        archive = {"markdown": "# 历史草稿", "sections": [], "acceptance": {}}
        accepted = _accepted_result("# 历史草稿\n\n## 增函数\n\n重新检索并审查后的内容。")

        async def fake_workflow(**kwargs):
            self.assertEqual(kwargs["resume_working_memory"]["markdown"], "# 历史草稿")
            self.assertEqual(
                kwargs["resume_working_memory"]["study_materials_workflow"]["stage"],
                "research",
            )
            return accepted

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=archive),
        ), patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(side_effect=fake_workflow),
            create=True,
        ) as run_workflow, patch.object(
            orchestrator,
            "upsert_study_archive",
            new=AsyncMock(),
        ), patch.object(orchestrator.task_runtime, "append_event", new=AsyncMock()), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        run_workflow.assert_awaited_once()
        complete.assert_awaited_once()

    async def test_continue_task_modes_reuse_workflow_snapshot(self) -> None:
        from backend.generation.study_materials import orchestrator

        workflow = {
            "version": 1,
            "stage": "review",
            "last_failure": {"stage": "review"},
            "preset": "standard",
            "markdown": "# 草稿",
        }
        snapshot = {
            "task_id": "study-4",
            "user_id": "u-1",
            "query": "函数单调性",
            "subject": "高中数学",
            "options": {"preset": "standard"},
            "iterations_done": 1,
            "last_failed_stage": "write",
            "resume_working_memory": {
                "markdown": "# 草稿",
                "assemble_study_archive": "# 草稿",
                "md_url": "/media/generated/m.md",
                "study_materials_workflow": workflow,
                "step_results": [
                    {"step_id": "s2", "tool": "review_content", "success": False, "error": "boom"},
                ],
            },
        }

        async def fake_create_task(**kwargs):
            return SimpleNamespace(
                task_id=kwargs["task_id"],
                user_id=kwargs["user_id"],
                request=kwargs["request"],
                meta=kwargs["meta"],
                parent_task_id=kwargs.get("parent_task_id"),
                status="running",
                created_at_s=1.0,
                updated_at_s=1.0,
            )

        expected_stages = {
            "improve": "review",
            "deepen_research": "research",
            "resume_failed_stage": "review",
            "retry_search": "research",
            "replan_from_failure": "plan",
        }
        for mode, expected_stage in expected_stages.items():
            with self.subTest(mode=mode):
                manager = StudyMaterialsTaskManager()
                with patch.object(manager, "_load_snapshot", return_value=dict(snapshot)), patch.object(
                    orchestrator,
                    "db_get_task",
                    new=AsyncMock(return_value={"status": "failed"}),
                ), patch(
                    "backend.generation.study_materials.orchestrator.task_runtime.create_task",
                    new=AsyncMock(side_effect=fake_create_task),
                ), patch.object(manager, "_persist_snapshot"):
                    new_task = await manager.continue_task(task_id="study-4", user_id="u-1", mode=mode)

                nested = new_task.meta["resume_working_memory"]["study_materials_workflow"]
                self.assertEqual(nested["stage"], expected_stage)

    def test_stream_tool_result_recovery_still_builds_resume_snapshot(self) -> None:
        from backend.generation.study_materials.orchestrator import _update_codex_stream_resume_state

        meta: dict = {}
        updated = _update_codex_stream_resume_state(
            meta=meta,
            tool_name="assemble_study_archive",
            event_data={"id": "call-1", "content": {"markdown": "# 部分草稿"}, "is_error": False},
            query="函数单调性",
            subject="高中数学",
            options={"preset": "standard"},
        )

        self.assertTrue(updated)
        self.assertEqual(meta["resume_working_memory"]["markdown"], "# 部分草稿")

    def test_merge_resume_working_memory_keeps_streamed_metadata(self) -> None:
        from backend.generation.study_materials.orchestrator import _merge_resume_working_memory

        existing = {
            "markdown": "# 草稿 v1",
            "assemble_study_archive": "# 草稿 v1",
            "md_url": "/media/generated/draft.md",
            "step_results": [{"step_id": "s1", "tool": "assemble_study_archive", "success": True}],
        }
        incoming = {
            "markdown": "# 草稿 v2",
            "assemble_study_archive": "# 草稿 v2",
            "step_results": [{"step_id": "s2", "tool": "review_content", "success": True}],
        }

        merged = _merge_resume_working_memory(existing, incoming)

        self.assertEqual(merged["markdown"], "# 草稿 v2")
        self.assertEqual(merged["md_url"], "/media/generated/draft.md")
        self.assertEqual(len(merged["step_results"]), 2)


if __name__ == "__main__":
    unittest.main()
