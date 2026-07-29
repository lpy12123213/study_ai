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
        options = {
            "preset": "standard",
            "requirements": "保留要求",
            "with_questions": True,
            "with_diagrams": False,
            "enable_extra_tools": True,
            "max_points": 2,
        }
        task = _task(
            options=options,
            meta={"agent_run_spec": build_study_materials_agent_spec(query="函数单调性", options=options).to_dict()},
        )
        accepted = _accepted_result()
        workflow_kwargs: dict = {}

        async def fake_workflow(**kwargs):
            workflow_kwargs.update(kwargs)
            await kwargs["event_sink"](
                {"type": "workflow_stage", "event": "workflow_stage", "data": {"stage": "review"}}
            )
            await kwargs["checkpoint_sink"](accepted["workflow"], accepted["resume_working_memory"])
            return accepted

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime"}, clear=False), patch.object(orchestrator, "AgentCore", side_effect=AssertionError("legacy AgentCore should not run")), patch.object(
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
        self.assertEqual(workflow_kwargs.get("options"), options)
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

        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime"}, clear=False), patch.object(orchestrator, "AgentCore", side_effect=AssertionError("legacy AgentCore should not run")), patch.object(
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
        self.assertTrue(fail.await_args.kwargs.get("emit_event", True))

    async def test_stage_result_failure_emits_terminal_error_event(self) -> None:
        from backend.generation.study_materials import orchestrator
        from backend.generation.study_materials.codex_stages import StageResultError

        manager = StudyMaterialsTaskManager()
        task = _task(task_id="study-stage-fail")
        failure = StageResultError(
            "invalid_stage_result",
            stage="draft",
            detail="stage_contract_mismatch",
        )

        async def fake_fail(runtime_task, *_args, **_kwargs):
            runtime_task.status = "failed"

        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime"}, clear=False), patch.object(
            orchestrator,
            "AgentCore",
            side_effect=AssertionError("legacy AgentCore should not run"),
        ), patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(side_effect=failure),
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
        self.assertEqual(fail.await_args.kwargs["error"]["stage"], "draft")
        self.assertEqual(fail.await_args.kwargs["error"]["detail"], "stage_contract_mismatch")
        self.assertTrue(fail.await_args.kwargs.get("emit_event", True))

    async def test_run_task_defaults_to_legacy_agent_core_when_runtime_unset(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task()

        async def fake_agent_run(*_args, **_kwargs):
            yield {"event": "done", "data": {"material": {"topic": "函数单调性", "iteration": 1, "markdown": "# 函数单调性"}}}

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        agent = SimpleNamespace(run=fake_agent_run, last_context=None)

        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": ""}, clear=False), patch.object(
            orchestrator,
            "AgentCore",
            return_value=agent,
        ) as agent_cls, patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(side_effect=AssertionError("codex workflow should not run")),
            create=True,
        ), patch.object(orchestrator.task_runtime, "append_event", new=AsyncMock()), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(
            orchestrator.task_runtime,
            "fail_task",
            new=AsyncMock(),
        ) as fail, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        agent_cls.assert_called_once_with()
        complete.assert_awaited_once()
        fail.assert_not_awaited()

    async def test_legacy_done_with_empty_material_fails_honestly(self) -> None:
        """legacy 路径工具失败被 ReAct 吞掉后，done 里空 markdown 不得标 completed。"""

        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task()

        async def fake_agent_run(*_args, **_kwargs):
            yield {"event": "done", "data": {"material": {"topic": "函数单调性", "iteration": 1, "markdown": "  "}}}

        agent = SimpleNamespace(run=fake_agent_run, last_context=None)

        async def fake_fail(runtime_task, *_args, **_kwargs):
            # 真实 fail_task 会把任务置为 failed，外层 finally 据此不再二次失败。
            runtime_task.status = "failed"

        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": ""}, clear=False), patch.object(
            orchestrator,
            "AgentCore",
            return_value=agent,
        ), patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(orchestrator.task_runtime, "append_event", new=AsyncMock()) as append_event, patch.object(
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
        self.assertEqual(fail.await_args.kwargs["error"]["code"], "empty_material")
        recovery_events = [
            call.args[1] for call in append_event.await_args_list if call.args[1].get("event") == "recovery_available"
        ]
        self.assertTrue(recovery_events)
        self.assertEqual(recovery_events[0]["data"]["code"], "empty_material")
        self.assertTrue(recovery_events[0]["data"]["recoverable"])

    def test_study_materials_codex_enabled_defaults_off(self) -> None:
        from backend.generation.study_materials.orchestrator import _study_materials_codex_enabled

        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": ""}, clear=False):
            self.assertFalse(_study_materials_codex_enabled())
        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "legacy"}, clear=False):
            self.assertFalse(_study_materials_codex_enabled())
        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime"}, clear=False):
            self.assertTrue(_study_materials_codex_enabled())

    async def test_fix_export_falls_through_to_legacy_agent_core_without_workflow_state(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task(
            task_id="study-legacy-fix-export",
            options={"preset": "standard", "continue_mode": "fix_export"},
            meta={"resume_working_memory": {"markdown": "# 旧稿", "assemble_study_archive": "# 旧稿"}},
        )

        async def fake_agent_run(*_args, **_kwargs):
            yield {"event": "done", "data": {"material": {"topic": "函数单调性", "iteration": 2, "markdown": "# 函数单调性"}}}

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        agent = SimpleNamespace(run=fake_agent_run, last_context=None)

        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": ""}, clear=False), patch.object(
            orchestrator,
            "AgentCore",
            return_value=agent,
        ) as agent_cls, patch.object(
            orchestrator,
            "_export_markdown_to_media",
            new=AsyncMock(),
        ) as export, patch.object(orchestrator.task_runtime, "append_event", new=AsyncMock()), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(
            orchestrator.task_runtime,
            "fail_task",
            new=AsyncMock(),
        ) as fail, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        export.assert_not_awaited()
        agent_cls.assert_called_once_with()
        complete.assert_awaited_once()
        fail.assert_not_awaited()

    async def test_current_accepted_local_archive_keeps_fast_path(self) -> None:
        from datetime import datetime, timezone

        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task(options={"preset": "standard"})
        markdown = _accepted_result()["material"]["markdown"]
        archive = {
            "markdown": markdown,
            "sections": [],
            "acceptance": _accepted_result()["acceptance"],
            # 真实仓库行总会带 created_at；B10 新鲜度预算把缺失时间戳按陈旧处理。
            "created_at": datetime.now(timezone.utc).isoformat(),
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

        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime"}, clear=False), patch.object(
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

    async def test_fix_export_republishes_accepted_markdown_without_codex(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        accepted = _accepted_result()
        markdown = accepted["material"]["markdown"]
        task = _task(
            task_id="study-fix-export",
            options={"preset": "standard", "continue_mode": "fix_export"},
            meta={"resume_working_memory": accepted["resume_working_memory"]},
        )

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.object(
            orchestrator,
            "_export_markdown_to_media",
            new=AsyncMock(return_value={"md_url": "/media/generated/refreshed.md", "md_filename": "refreshed.md"}),
        ) as export, patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(),
        ) as run_workflow, patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        export.assert_awaited_once_with(markdown=markdown, user_id="u-1")
        run_workflow.assert_not_awaited()
        complete.assert_awaited_once()
        result = complete.await_args.kwargs["result"]
        self.assertEqual(result["md_url"], "/media/generated/refreshed.md")
        self.assertEqual(result["resume_working_memory"]["md_url"], "/media/generated/refreshed.md")
        self.assertEqual(result["material"]["markdown"], markdown)

    async def test_skip_export_completes_accepted_markdown_without_publishing(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        accepted = _accepted_result()
        markdown = accepted["material"]["markdown"]
        task = _task(
            task_id="study-skip-export",
            options={"preset": "standard", "continue_mode": "skip_export"},
            meta={"resume_working_memory": accepted["resume_working_memory"]},
        )

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.object(orchestrator, "_export_markdown_to_media", new=AsyncMock()) as export, patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(),
        ) as run_workflow, patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        export.assert_not_awaited()
        run_workflow.assert_not_awaited()
        complete.assert_awaited_once()
        self.assertEqual(complete.await_args.kwargs["result"]["material"]["markdown"], markdown)

    async def test_export_continuation_requires_current_acceptance(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        accepted = _accepted_result()
        resume = dict(accepted["resume_working_memory"])
        resume["study_materials_workflow"] = {
            **accepted["workflow"],
            "acceptance": {},
        }
        task = _task(
            task_id="study-invalid-export",
            options={"preset": "standard", "continue_mode": "fix_export"},
            meta={"resume_working_memory": resume},
        )

        async def fake_fail(runtime_task, *_args, **_kwargs):
            runtime_task.status = "failed"

        with patch.object(orchestrator, "_export_markdown_to_media", new=AsyncMock()) as export, patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(),
        ) as run_workflow, patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(),
        ) as complete, patch.object(
            orchestrator.task_runtime,
            "fail_task",
            new=AsyncMock(side_effect=fake_fail),
        ) as fail, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        export.assert_not_awaited()
        run_workflow.assert_not_awaited()
        complete.assert_not_awaited()
        fail.assert_awaited_once()
        self.assertEqual(fail.await_args.args[1], "accepted_content_required")
        self.assertTrue(fail.await_args.kwargs.get("emit_event", True))

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

    async def test_codex_stage_result_missing_falls_back_to_legacy_agent_explicitly(self) -> None:
        """B2: StageResultError(stage_result_missing) + fallback 开启 → 显式回退 legacy。

        必须有日志与任务事件，且 AgentCore 真正跑起来完成任务（不再靠位置静默落入）。
        """

        import logging

        from backend.generation.study_materials import orchestrator
        from backend.generation.study_materials.codex_stages import StageResultError

        # 全量套件里 alembic env.py 的 fileConfig（disable_existing_loggers=True，
        # 见 test_database_alembic）可能已把该 logger 置为 disabled；assertLogs
        # 只恢复 handlers/level/propagate，不会复位 disabled，这里显式复位，
        # 保证本用例与测试执行顺序无关。
        logging.getLogger("backend.generation.study_materials.orchestrator").disabled = False

        manager = StudyMaterialsTaskManager()
        task = _task(task_id="study-fallback")
        failure = StageResultError(
            "invalid_stage_result",
            stage="draft",
            detail="stage_result_missing",
        )

        async def fake_agent_run(*_args, **_kwargs):
            yield {"event": "done", "data": {"material": {"topic": "函数单调性", "iteration": 1, "markdown": "# 函数单调性"}}}

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        agent = SimpleNamespace(run=fake_agent_run, last_context=None)

        with patch.dict(
            "os.environ",
            {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime", "CODEX_RUNTIME_FALLBACK_LEGACY": "1"},
            clear=False,
        ), patch.object(
            orchestrator,
            "AgentCore",
            return_value=agent,
        ) as agent_cls, patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(side_effect=failure),
            create=True,
        ), patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ) as append_event, patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(
            orchestrator.task_runtime,
            "fail_task",
            new=AsyncMock(),
        ) as fail, patch.object(manager, "_persist_snapshot"):
            with self.assertLogs("backend.generation.study_materials.orchestrator", level="WARNING") as logs:
                await manager._run_task(task)

        self.assertTrue(any("study_materials_codex_fallback_to_legacy" in line for line in logs.output))
        fallback_events = [
            call.args[1]
            for call in append_event.await_args_list
            if str(call.args[1].get("event") or call.args[1].get("type") or "") == "codex_fallback_to_legacy"
        ]
        self.assertEqual(len(fallback_events), 1)
        self.assertEqual(fallback_events[0]["data"]["stage"], "draft")
        self.assertEqual(fallback_events[0]["data"]["detail"], "stage_result_missing")
        agent_cls.assert_called_once_with()
        complete.assert_awaited_once()
        fail.assert_not_awaited()

    async def test_fix_export_failure_still_completes_with_markdown(self) -> None:
        """B5: 导出连续失败不拖垮任务——记录 export_error、发事件、用 markdown 完成。"""

        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        accepted = _accepted_result()
        markdown = accepted["material"]["markdown"]
        task = _task(
            task_id="study-fix-export-fail",
            options={"preset": "standard", "continue_mode": "fix_export"},
            meta={"resume_working_memory": accepted["resume_working_memory"]},
        )

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.object(
            orchestrator,
            "_export_markdown_to_media",
            new=AsyncMock(side_effect=RuntimeError("disk full")),
        ) as export, patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ) as append_event, patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(
            orchestrator.task_runtime,
            "fail_task",
            new=AsyncMock(),
        ) as fail, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        self.assertEqual(export.await_count, 2)
        complete.assert_awaited_once()
        fail.assert_not_awaited()
        result = complete.await_args.kwargs["result"]
        self.assertEqual(result["material"]["markdown"], markdown)
        self.assertNotIn("md_url", result)
        self.assertEqual(task.meta.get("export_error"), "disk full")
        export_events = [
            call.args[1]
            for call in append_event.await_args_list
            if str(call.args[1].get("event") or "") == "export_failed"
        ]
        self.assertEqual(len(export_events), 1)
        self.assertEqual(export_events[0]["data"]["error"], "disk full")

    async def test_fix_export_retries_once_and_recovers(self) -> None:
        """B5: 首次导出失败、第二次成功 → 正常带上 md_url 完成，且无 export_error。"""

        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        accepted = _accepted_result()
        task = _task(
            task_id="study-fix-export-retry",
            options={"preset": "standard", "continue_mode": "fix_export"},
            meta={"resume_working_memory": accepted["resume_working_memory"]},
        )

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.object(
            orchestrator,
            "_export_markdown_to_media",
            new=AsyncMock(
                side_effect=[RuntimeError("boom"), {"md_url": "/media/generated/retry.md", "md_filename": "retry.md"}]
            ),
        ) as export, patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        self.assertEqual(export.await_count, 2)
        complete.assert_awaited_once()
        self.assertEqual(complete.await_args.kwargs["result"]["md_url"], "/media/generated/retry.md")
        self.assertNotIn("export_error", task.meta)

    async def test_reused_archive_export_failure_still_completes(self) -> None:
        """B5: 归档快速通道导出失败 → 仍按复用结果完成，不让任务失败。"""

        from datetime import datetime, timezone

        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task(options={"preset": "standard"})
        archive = {
            "markdown": _accepted_result()["material"]["markdown"],
            "sections": [],
            "acceptance": _accepted_result()["acceptance"],
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            new=AsyncMock(side_effect=RuntimeError("cdn down")),
        ), patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(
            orchestrator.task_runtime,
            "fail_task",
            new=AsyncMock(),
        ) as fail, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        complete.assert_awaited_once()
        fail.assert_not_awaited()
        self.assertTrue(complete.await_args.kwargs["result"]["reused_local_archive"])
        self.assertEqual(task.meta.get("export_error"), "cdn down")

    async def test_stale_archive_candidate_has_real_or_omitted_coverage_map(self) -> None:
        """B18: 候选草稿的 coverage_map 必须来自真实小节拆分；匹配不到时省略该键。"""

        from backend.generation.study_materials import orchestrator

        accepted = _accepted_result("# 历史草稿\n\n正文没有可匹配的知识点二级标题。")
        captured: dict = {}

        async def run_case(archive: dict) -> dict:
            manager = StudyMaterialsTaskManager()
            task = _task(options={"preset": "standard"})

            async def fake_workflow(**kwargs):
                captured.update(kwargs)
                return accepted

            async def fake_complete(runtime_task, **_kwargs):
                runtime_task.status = "completed"

            with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime"}, clear=False), patch.object(
                orchestrator,
                "get_study_archive_by_fingerprint",
                new=AsyncMock(return_value=archive),
            ), patch.object(
                orchestrator,
                "run_study_materials_workflow",
                new=AsyncMock(side_effect=fake_workflow),
                create=True,
            ), patch.object(
                orchestrator,
                "upsert_study_archive",
                new=AsyncMock(),
            ), patch.object(orchestrator.task_runtime, "append_event", new=AsyncMock()), patch.object(
                orchestrator.task_runtime,
                "complete_task",
                new=AsyncMock(side_effect=fake_complete),
            ), patch.object(manager, "_persist_snapshot"):
                await manager._run_task(task)
            # 预审产出（传给 workflow 的续作快照）才是断言对象——最终 meta 会被结果覆盖。
            return captured["resume_working_memory"]["study_materials_workflow"]

        # 无 ## 小节：point_titles 回退到 query，整篇匹配不到 → coverage_map 省略。
        state = await run_case({"markdown": "# 历史草稿", "sections": [], "acceptance": {}})
        self.assertFalse(any((state.get("coverage_map") or {}).values()))
        # 有编号二级标题且 sections 指明知识点：真实拆分得到逐知识点布尔值。
        state = await run_case(
            {
                "markdown": "# 函数单调性\n\n## 1、增函数\n\n增函数的定义与性质。",
                "sections": [{"knowledge_point": "增函数"}],
                "acceptance": {},
            }
        )
        self.assertEqual(state.get("coverage_map"), {"kp-1": True})

    async def test_local_archive_with_mismatched_content_options_is_not_reused(self) -> None:
        """B10: 同指纹归档但内容选项不同（with_questions）→ 不得直接复用。"""

        from datetime import datetime, timezone

        from backend.generation.study_materials import orchestrator
        from backend.generation.study_materials.quality_gate import build_acceptance_record, draft_hash

        manager = StudyMaterialsTaskManager()
        markdown = _accepted_result()["material"]["markdown"]
        task = _task(options={"preset": "standard", "with_questions": True})
        archive = {
            "markdown": markdown,
            "sections": [],
            "acceptance": build_acceptance_record(
                report={"passed": True, "draft_hash": draft_hash(markdown), "failed_checks": []},
                preset="standard",
                options={"with_questions": False},
            ),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        accepted = _accepted_result()

        async def fake_workflow(**kwargs):
            return accepted

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime"}, clear=False), patch.object(
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
        ), patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        run_workflow.assert_awaited_once()

    async def test_local_archive_older_than_max_age_is_not_reused(self) -> None:
        """B10: 归档超过新鲜度预算 → 走候选草稿路径；max_age=0 保持旧行为。"""

        from datetime import datetime, timedelta, timezone

        from backend.generation.study_materials import orchestrator

        markdown = _accepted_result()["material"]["markdown"]
        old_archive = {
            "markdown": markdown,
            "sections": [],
            "acceptance": _accepted_result()["acceptance"],
            "created_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
        }
        accepted = _accepted_result()

        async def run_with_env(max_age: str) -> tuple[AsyncMock, AsyncMock]:
            manager = StudyMaterialsTaskManager()
            task = _task(options={"preset": "standard"})

            async def fake_workflow(**kwargs):
                return accepted

            async def fake_complete(runtime_task, **_kwargs):
                runtime_task.status = "completed"

            with patch.dict(
                "os.environ",
                {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime", "STUDY_MATERIALS_ARCHIVE_MAX_AGE_S": max_age},
                clear=False,
            ), patch.object(
                orchestrator,
                "get_study_archive_by_fingerprint",
                new=AsyncMock(return_value=old_archive),
            ), patch.object(
                orchestrator,
                "run_study_materials_workflow",
                new=AsyncMock(side_effect=fake_workflow),
                create=True,
            ) as run_workflow, patch.object(
                orchestrator,
                "_export_markdown_to_media",
                new=AsyncMock(return_value={"md_url": "/m.md", "md_filename": "m.md"}),
            ), patch.object(
                orchestrator,
                "upsert_study_archive",
                new=AsyncMock(),
            ), patch.object(orchestrator.task_runtime, "append_event", new=AsyncMock()), patch.object(
                orchestrator.task_runtime,
                "complete_task",
                new=AsyncMock(side_effect=fake_complete),
            ) as complete, patch.object(manager, "_persist_snapshot"):
                await manager._run_task(task)
            return run_workflow, complete

        # 30 天前的归档在 1 小时预算下不得直接复用。
        run_workflow, complete = await run_with_env("3600")
        run_workflow.assert_awaited_once()
        # max_age=0 关闭时间过期，保持旧的直接复用行为。
        run_workflow, complete = await run_with_env("0")
        run_workflow.assert_not_awaited()
        self.assertTrue(complete.await_args.kwargs["result"]["reused_local_archive"])

    async def test_degraded_workflow_result_passes_through_done_event_and_result(self) -> None:
        """B6: degraded / material.passed / material.issues 原样进 done 事件与任务结果。"""

        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task(task_id="study-degraded")
        degraded = _accepted_result()
        degraded["degraded"] = True
        degraded["acceptance"] = {}
        degraded["material"] = {
            **degraded["material"],
            "passed": False,
            "issues": ["independent_review_failed"],
        }

        async def fake_workflow(**kwargs):
            return degraded

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime"}, clear=False), patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(side_effect=fake_workflow),
            create=True,
        ), patch.object(
            orchestrator,
            "upsert_study_archive",
            new=AsyncMock(),
        ), patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ) as append_event, patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)

        complete.assert_awaited_once()
        for payload in (
            complete.await_args.kwargs["result"],
            next(
                call.args[1]["data"]
                for call in append_event.await_args_list
                if str(call.args[1].get("event") or "") == "done"
            ),
        ):
            self.assertTrue(payload["degraded"])
            self.assertFalse(payload["material"]["passed"])
            self.assertEqual(payload["material"]["issues"], ["independent_review_failed"])

    async def test_research_tool_outage_code_reaches_recovery_event_and_error_payload(self) -> None:
        """B6: WorkflowFailure(research_tool_outage) 的 code 原样进 recovery_available 事件与错误载荷。"""

        from backend.generation.study_materials import orchestrator
        from backend.generation.study_materials.workflow import WorkflowFailure

        manager = StudyMaterialsTaskManager()
        task = _task(task_id="study-outage")

        async def fake_workflow(**kwargs):
            await kwargs["event_sink"](
                {
                    "type": "recovery_available",
                    "event": "recovery_available",
                    "data": {
                        "code": "research_tool_outage",
                        "stage": "research",
                        "issues": ["tool_unavailable:web_search_knowledge"],
                        "recoverable": True,
                    },
                }
            )
            raise WorkflowFailure(
                "research_tool_outage",
                stage="research",
                issues=["tool_unavailable:web_search_knowledge"],
            )

        async def fake_fail(runtime_task, *_args, **_kwargs):
            runtime_task.status = "failed"

        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime"}, clear=False), patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "run_study_materials_workflow",
            new=AsyncMock(side_effect=fake_workflow),
            create=True,
        ), patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ) as append_event, patch.object(
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
        self.assertEqual(fail.await_args.args[1], "research_tool_outage")
        self.assertEqual(fail.await_args.kwargs["error"]["code"], "research_tool_outage")
        recovery_events = [
            call.args[1]
            for call in append_event.await_args_list
            if str(call.args[1].get("type") or call.args[1].get("event") or "") == "recovery_available"
        ]
        self.assertEqual(len(recovery_events), 1)
        self.assertEqual(recovery_events[0]["data"]["code"], "research_tool_outage")

    @staticmethod
    def _continuable_snapshot() -> dict:
        return {
            "task_id": "study-canceled",
            "user_id": "u-1",
            "query": "函数单调性",
            "subject": "高中数学",
            "options": {"preset": "standard"},
            "user_iteration": 1,
            "iterations_done": 1,
            "resume_working_memory": {
                "markdown": "# 成稿",
                "assemble_study_archive": "# 成稿",
                "study_materials_workflow": {
                    "version": 1,
                    "stage": "completed",
                    "preset": "standard",
                    "markdown": "# 成稿",
                    "acceptance": {},
                    "last_failure": {},
                },
            },
        }

    @staticmethod
    async def _fake_create_task(**kwargs):
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

    async def test_continue_task_accepts_canceled_task_with_rebuildable_memory(self) -> None:
        """B3: 已取消任务（前端"继续生成"）必须可续作——只有真正 running 才被拦截。"""

        from backend.generation.study_materials import orchestrator

        for db_status, expect_error in (("canceled", None), ("cancelled", None), ("running", "task_running")):
            with self.subTest(db_status=db_status):
                manager = StudyMaterialsTaskManager()
                with patch.object(manager, "_load_snapshot", return_value=self._continuable_snapshot()), patch.object(
                    orchestrator,
                    "db_get_task",
                    new=AsyncMock(return_value={"status": db_status}),
                ), patch(
                    "backend.generation.study_materials.orchestrator.task_runtime.create_task",
                    new=AsyncMock(side_effect=self._fake_create_task),
                ), patch.object(manager, "_persist_snapshot"):
                    if expect_error:
                        with self.assertRaisesRegex(ValueError, expect_error):
                            await manager.continue_task(task_id="study-canceled", user_id="u-1", mode="improve")
                    else:
                        new_task = await manager.continue_task(task_id="study-canceled", user_id="u-1", mode="improve")
                        self.assertEqual(new_task.parent_task_id, "study-canceled")

    async def test_continue_task_raises_not_found_only_when_db_row_gone(self) -> None:
        """B3: 404 只在 DB 任务行也不存在时发生；行在则可从结果载荷重建续作上下文。"""

        from backend.generation.study_materials import orchestrator

        # DB 行也 gone → task_not_found。
        manager = StudyMaterialsTaskManager()
        with patch.object(manager, "_load_snapshot", return_value=None), patch.object(
            orchestrator,
            "db_get_task",
            new=AsyncMock(return_value=None),
        ), patch.object(manager, "_persist_snapshot"):
            with self.assertRaisesRegex(ValueError, "task_not_found"):
                await manager.continue_task(task_id="study-gone", user_id="u-1", mode="improve")

        # DB 行在且结果载荷可重建 → 正常续作（冷续作）。
        manager = StudyMaterialsTaskManager()
        db_task = {
            "status": "completed",
            "request": {"query": "函数单调性", "subject": "高中数学", "options": {"preset": "standard"}},
            "result": {
                "material": {
                    "topic": "函数单调性",
                    "subject": "高中数学",
                    "preset": "standard",
                    "markdown": "# 成稿",
                }
            },
        }
        with patch.object(manager, "_load_snapshot", return_value=None), patch.object(
            orchestrator,
            "db_get_task",
            new=AsyncMock(return_value=db_task),
        ), patch(
            "backend.generation.study_materials.orchestrator.task_runtime.create_task",
            new=AsyncMock(side_effect=self._fake_create_task),
        ), patch.object(manager, "_persist_snapshot"):
            new_task = await manager.continue_task(task_id="study-cold", user_id="u-1", mode="improve")

        self.assertEqual(new_task.parent_task_id, "study-cold")
        self.assertEqual(new_task.request["query"], "函数单调性")

    async def test_continue_task_deepen_research_sets_acceptance_preset_options(self) -> None:
        """B8: deepen_research 把 preset 提到 research，同时记下原 preset 供验收门使用。"""

        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        with patch.object(manager, "_load_snapshot", return_value=self._continuable_snapshot()), patch.object(
            orchestrator,
            "db_get_task",
            new=AsyncMock(return_value={"status": "completed"}),
        ), patch(
            "backend.generation.study_materials.orchestrator.task_runtime.create_task",
            new=AsyncMock(side_effect=self._fake_create_task),
        ), patch.object(manager, "_persist_snapshot"):
            new_task = await manager.continue_task(task_id="study-canceled", user_id="u-1", mode="deepen_research")

        options = new_task.request["options"]
        self.assertEqual(options["preset"], "research")
        self.assertEqual(options["acceptance_preset"], "standard")
        self.assertEqual(options["continue_mode"], "deepen_research")

    async def test_get_task_db_fallback_preserves_ownership_and_marks_unresumable(self) -> None:
        """B3: 无快照时 get_task 从 DB 构建视图——归属校验保留，无可重建内容时 resume 为空。"""

        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        db_task = {
            "status": "completed",
            "request": {"query": "函数单调性", "subject": "高中数学", "options": {"preset": "standard"}},
            "result": {},
            "last_seq": 7,
        }

        with patch.object(manager, "_load_snapshot", return_value=None), patch.object(
            orchestrator,
            "db_get_task",
            new=AsyncMock(return_value=db_task),
        ) as db_lookup:
            # 无 user_id 无法做归属校验 → 宁可 404。
            self.assertIsNone(await manager.get_task("study-db"))
            db_lookup.assert_not_awaited()

            view = await manager.get_task("study-db", user_id="u-1")

        self.assertIsNotNone(view)
        self.assertEqual(view.status, "completed")
        self.assertEqual(view.user_id, "u-1")
        # 结果载荷无可重建内容 → resume_working_memory 为空（API 层据此 resumable=False）。
        self.assertFalse(view.resume_working_memory)
        self.assertEqual(view.last_seq, 7)

        # DB 行也 gone（含越权访问被仓库层拦截的情形）→ None → API 404。
        with patch.object(manager, "_load_snapshot", return_value=None), patch.object(
            orchestrator,
            "db_get_task",
            new=AsyncMock(return_value=None),
        ):
            self.assertIsNone(await manager.get_task("study-db", user_id="u-1"))


if __name__ == "__main__":
    unittest.main()
