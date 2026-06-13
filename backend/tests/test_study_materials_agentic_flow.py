from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.generation.agentic.study_materials import build_study_materials_agent_spec
from backend.generation.study_materials.orchestrator import StudyMaterialsTaskManager
from backend.llm.prompts import create_default_prompt_registry


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

        with patch("backend.generation.study_materials.orchestrator.task_runtime.create_task", new=AsyncMock(side_effect=fake_create_task)):
            with patch.object(manager, "_persist_snapshot"):
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

    async def test_run_task_uses_codex_runtime_without_agent_core(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = SimpleNamespace(
            task_id="study-1",
            user_id="u-1",
            request={"query": "函数单调性", "subject": "高中数学", "options": {}},
            meta={
                "agent_run_spec": build_study_materials_agent_spec(
                    query="函数单调性",
                    subject="高中数学",
                    options={},
                ).to_dict()
            },
            parent_task_id=None,
            status="running",
        )

        async def fake_codex_events(*_args, **_kwargs):
            yield {"event": "status", "type": "status", "data": {"content": "Codex runtime", "runtime": "codex_runtime"}}
            yield {"event": "done", "type": "done", "data": {"material": {"topic": "函数单调性"}, "runtime": "codex_runtime"}}

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.object(orchestrator, "AgentCore", side_effect=AssertionError("legacy AgentCore should not run")), patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "run_codex_runtime_agent_events",
            side_effect=fake_codex_events,
            create=True,
        ) as codex_run, patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(
            manager,
            "_persist_snapshot",
        ):
            await manager._run_task(task)

        codex_run.assert_called_once()
        complete.assert_awaited_once()

    async def test_run_task_codex_done_persists_resume_state_and_archive(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = SimpleNamespace(
            task_id="study-2",
            user_id="u-1",
            request={"query": "函数单调性", "subject": "高中数学", "options": {}},
            meta={
                "agent_run_spec": build_study_materials_agent_spec(
                    query="函数单调性",
                    subject="高中数学",
                    options={},
                ).to_dict()
            },
            parent_task_id=None,
            status="running",
        )

        async def fake_codex_events(*_args, **_kwargs):
            yield {
                "event": "done",
                "type": "done",
                "data": {
                    "runtime": "codex_runtime",
                    "material": {
                        "topic": "函数单调性",
                        "subject": "高中数学",
                        "markdown": "# 函数单调性\n\n资料正文",
                        "md_url": "/media/generated/m.md",
                        "iteration": 2,
                        "error": None,
                    },
                },
            }

        async def fake_complete(runtime_task, **_kwargs):
            runtime_task.status = "completed"

        with patch.object(orchestrator, "AgentCore", side_effect=AssertionError("legacy AgentCore should not run")), patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "run_codex_runtime_agent_events",
            side_effect=fake_codex_events,
        ), patch.object(
            orchestrator,
            "upsert_study_archive",
            new=AsyncMock(),
        ) as upsert, patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ), patch.object(
            orchestrator.task_runtime,
            "complete_task",
            new=AsyncMock(side_effect=fake_complete),
        ) as complete, patch.object(
            manager,
            "_persist_snapshot",
        ) as persist:
            await manager._run_task(task)

        complete.assert_awaited_once()
        upsert.assert_awaited_once()
        self.assertEqual(upsert.await_args.kwargs["topic"], "函数单调性")
        self.assertEqual(upsert.await_args.kwargs["subject"], "高中数学")
        self.assertIn("函数单调性", upsert.await_args.kwargs["markdown"])

        wm = task.meta.get("resume_working_memory")
        self.assertIsInstance(wm, dict)
        self.assertEqual(wm["markdown"], "# 函数单调性\n\n资料正文")
        self.assertEqual(wm["md_url"], "/media/generated/m.md")
        self.assertEqual(task.meta.get("iterations_done"), 2)
        self.assertTrue(any(call.kwargs.get("force") for call in persist.call_args_list))

    async def test_run_task_codex_error_keeps_resume_state_for_continue(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = SimpleNamespace(
            task_id="study-3",
            user_id="u-1",
            request={"query": "函数单调性", "subject": "高中数学", "options": {}},
            meta={},
            parent_task_id=None,
            status="running",
        )

        async def fake_codex_events(*_args, **_kwargs):
            yield {
                "event": "error",
                "type": "error",
                "data": {
                    "code": "codex_runtime_agent_failed",
                    "message": "compile failed",
                    "result": {
                        "resume_working_memory": {
                            "markdown": "# 部分草稿",
                            "step_results": [
                                {"step_id": "s1", "tool": "assemble_study_archive", "success": True},
                                {"step_id": "s2", "tool": "compile_latex_to_pdf", "success": False, "error": "boom"},
                            ],
                        }
                    },
                },
            }

        async def fake_fail(runtime_task, *_args, **_kwargs):
            runtime_task.status = "failed"

        with patch.object(orchestrator, "AgentCore", side_effect=AssertionError("legacy AgentCore should not run")), patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "run_codex_runtime_agent_events",
            side_effect=fake_codex_events,
        ), patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ), patch.object(
            orchestrator.task_runtime,
            "fail_task",
            new=AsyncMock(side_effect=fake_fail),
        ) as fail, patch.object(
            manager,
            "_persist_snapshot",
        ) as persist:
            await manager._run_task(task)

        fail.assert_awaited_once()
        wm = task.meta.get("resume_working_memory")
        self.assertIsInstance(wm, dict)
        self.assertEqual(wm["markdown"], "# 部分草稿")
        self.assertEqual(task.meta.get("last_failed_stage"), "export")
        self.assertTrue(any(call.kwargs.get("force") for call in persist.call_args_list))

    async def test_run_task_codex_runtime_failure_recovers_from_streamed_tool_results(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = SimpleNamespace(
            task_id="study-3b",
            user_id="u-1",
            request={"query": "函数单调性", "subject": "高中数学", "options": {"preset": "standard"}},
            meta={
                "agent_run_spec": build_study_materials_agent_spec(
                    query="函数单调性",
                    subject="高中数学",
                    options={"preset": "standard"},
                ).to_dict()
            },
            parent_task_id=None,
            status="running",
        )

        async def fake_codex_events(*_args, **_kwargs):
            yield {
                "event": "tool_call",
                "type": "tool_call",
                "data": {"id": "call-1", "name": "assemble_study_archive", "arguments": {}},
            }
            yield {
                "event": "tool_result",
                "type": "tool_result",
                "data": {
                    "id": "call-1",
                    "content": {"markdown": "# 函数单调性\n\n部分草稿"},
                    "is_error": False,
                },
            }
            yield {
                "event": "tool_call",
                "type": "tool_call",
                "data": {"id": "call-2", "name": "compile_latex_to_pdf", "arguments": {}},
            }
            yield {
                "event": "tool_result",
                "type": "tool_result",
                "data": {
                    "id": "call-2",
                    "content": {"success": False, "error": "latex boom"},
                    "is_error": True,
                },
            }
            yield {
                "event": "error",
                "type": "error",
                "data": {"code": "codex_runtime_failed", "message": "Codex runtime exited with code 2."},
            }

        async def fake_fail(runtime_task, *_args, **_kwargs):
            runtime_task.status = "failed"

        with patch.object(orchestrator, "AgentCore", side_effect=AssertionError("legacy AgentCore should not run")), patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "run_codex_runtime_agent_events",
            side_effect=fake_codex_events,
        ), patch.object(
            orchestrator.task_runtime,
            "append_event",
            new=AsyncMock(),
        ), patch.object(
            orchestrator.task_runtime,
            "fail_task",
            new=AsyncMock(side_effect=fake_fail),
        ), patch.object(
            manager,
            "_persist_snapshot",
        ) as persist:
            await manager._run_task(task)

        wm = task.meta.get("resume_working_memory")
        self.assertIsInstance(wm, dict)
        self.assertEqual(wm.get("markdown"), "# 函数单调性\n\n部分草稿")
        self.assertEqual(wm.get("assemble_study_archive"), "# 函数单调性\n\n部分草稿")
        self.assertEqual(task.meta.get("last_failed_stage"), "export")
        self.assertEqual(task.meta.get("last_failed_step", {}).get("tool"), "compile_latex_to_pdf")
        self.assertTrue(any(call.kwargs.get("force") for call in persist.call_args_list))

    async def test_continue_task_modes_reuse_codex_snapshot(self) -> None:
        from backend.generation.study_materials import orchestrator

        snapshot = {
            "task_id": "study-4",
            "user_id": "u-1",
            "query": "函数单调性",
            "subject": "高中数学",
            "options": {"preset": "standard"},
            "iterations_done": 1,
            "last_failed_stage": "export",
            "resume_working_memory": {
                "markdown": "# 草稿",
                "assemble_study_archive": "# 草稿",
                "md_url": "/media/generated/m.md",
                "step_results": [
                    {"step_id": "s2", "tool": "compile_latex_to_pdf", "success": False, "error": "boom"},
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

        for mode, expect_md_url in (("fix_export", True), ("skip_export", True), ("resume_failed_stage", False)):
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

                self.assertEqual(new_task.parent_task_id, "study-4")
                self.assertEqual(new_task.request["options"]["continue_mode"], mode)
                self.assertEqual(new_task.meta.get("iteration_offset"), 1)
                self.assertEqual(new_task.meta.get("max_iterations"), 1)

                wm = new_task.meta.get("resume_working_memory")
                self.assertIsInstance(wm, dict)
                self.assertEqual(wm.get("markdown"), "# 草稿")
                self.assertEqual("md_url" in wm, expect_md_url)

                spec = new_task.meta.get("agent_run_spec")
                self.assertIsInstance(spec, dict)
                self.assertEqual(spec["resume_state"]["resume_working_memory"].get("markdown"), "# 草稿")
                self.assertEqual(spec["input_payload"]["options"]["continue_mode"], mode)

    def test_merge_resume_working_memory_keeps_streamed_metadata(self) -> None:
        """``done`` payload must not wipe out metadata accumulated during streaming.

        The streamed ``resume_working_memory`` typically captures intermediate
        artifacts (``md_url``, ``step_results``, tool-keyed outputs) that the
        final codex result omits. Merging—not replacing—is what keeps
        ``fix_export`` / ``improve`` continuations working.
        """

        from backend.generation.study_materials.orchestrator import _merge_resume_working_memory

        existing = {
            "markdown": "# 草稿 v1",
            "assemble_study_archive": "# 草稿 v1",
            "md_url": "/media/generated/draft.md",
            "step_results": [
                {"step_id": "s1", "tool": "assemble_study_archive", "success": True},
            ],
            "study_options": {"preset": "standard", "requirements": ""},
            "tool_call_log": ["assemble_study_archive"],
        }
        incoming = {
            "markdown": "# 草稿 v2",
            "assemble_study_archive": "# 草稿 v2",
            "study_options": {"preset": "deep", "requirements": "偏直观"},
            "step_results": [
                {"step_id": "s2", "tool": "revise_markdown", "success": True},
            ],
            "generate_study_material": {"topic": "x"},
        }

        merged = _merge_resume_working_memory(existing, incoming)

        # Final canonical content wins.
        self.assertEqual(merged["markdown"], "# 草稿 v2")
        self.assertEqual(merged["assemble_study_archive"], "# 草稿 v2")
        self.assertEqual(merged["study_options"], {"preset": "deep", "requirements": "偏直观"})

        # Streamed-only metadata survives.
        self.assertEqual(merged["md_url"], "/media/generated/draft.md")
        self.assertEqual(merged["tool_call_log"], ["assemble_study_archive"])

        # step_results are appended, not replaced, so debugging history is preserved.
        self.assertEqual(len(merged["step_results"]), 2)
        self.assertEqual(merged["step_results"][0]["step_id"], "s1")
        self.assertEqual(merged["step_results"][1]["step_id"], "s2")

        # New keys (generate_study_material) are merged in.
        self.assertEqual(merged["generate_study_material"], {"topic": "x"})

    def test_merge_resume_working_memory_skips_empty_incoming_values(self) -> None:
        from backend.generation.study_materials.orchestrator import _merge_resume_working_memory

        existing = {"markdown": "# existing", "md_url": "/u/x.md"}
        incoming = {"markdown": "", "md_url": None, "tex_url": "/u/x.tex"}

        merged = _merge_resume_working_memory(existing, incoming)

        self.assertEqual(merged["markdown"], "# existing")
        self.assertEqual(merged["md_url"], "/u/x.md")
        self.assertEqual(merged["tex_url"], "/u/x.tex")


if __name__ == "__main__":
    unittest.main()
