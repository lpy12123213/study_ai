"""T15 运行时收敛回归：author 为默认 runtime，decompose 默认关闭。

覆盖：
- ``STUDY_MATERIALS_AGENT_RUNTIME`` 未设置时 ``_run_task`` dispatch 到 author 流水线；
- 显式设 ``legacy`` 时仍走 legacy AgentCore 路径；
- ``STUDY_MATERIALS_WEB_DECOMPOSE`` 未设置且未显式传参时不再做子问题拆分。
"""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import backend.agent.tools.search.web_search_knowledge_impl as web_impl
from backend.agent.tools.search.web_search_knowledge import WebSearchKnowledgeToolsMixin
from backend.agent.types import CompressedContext, UserProfile
from backend.generation.study_materials.orchestrator import StudyMaterialsTaskManager


def _task(*, task_id: str = "study-runtime-1", options: dict | None = None, meta: dict | None = None):
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


class StudyMaterialsRuntimeDefaultTests(unittest.IsolatedAsyncioTestCase):
    async def _run_task_with_spies(self, task) -> dict:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()

        async def _mark_completed(ctx) -> None:
            ctx.task.status = "completed"

        spies = {
            "author": AsyncMock(side_effect=_mark_completed),
            "legacy": AsyncMock(side_effect=_mark_completed),
            "codex": AsyncMock(side_effect=_mark_completed),
        }
        with patch.object(
            StudyMaterialsTaskManager, "_run_author_staged", new=spies["author"]
        ), patch.object(
            StudyMaterialsTaskManager, "_run_legacy_agent", new=spies["legacy"]
        ), patch.object(
            StudyMaterialsTaskManager, "_run_codex_staged", new=spies["codex"]
        ), patch.object(
            orchestrator,
            "get_study_archive_by_fingerprint",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator.task_runtime,
            "fail_task",
            new=AsyncMock(),
        ) as fail, patch.object(manager, "_persist_snapshot"):
            await manager._run_task(task)
        spies["fail"] = fail
        return spies

    async def test_run_task_defaults_to_author_when_runtime_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=False) as environ:
            environ.pop("STUDY_MATERIALS_AGENT_RUNTIME", None)
            spies = await self._run_task_with_spies(_task())

        spies["author"].assert_awaited_once()
        spies["legacy"].assert_not_awaited()
        spies["codex"].assert_not_awaited()
        spies["fail"].assert_not_awaited()

    async def test_run_task_uses_legacy_when_runtime_explicitly_legacy(self) -> None:
        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "legacy"}, clear=False):
            spies = await self._run_task_with_spies(_task())

        spies["legacy"].assert_awaited_once()
        spies["author"].assert_not_awaited()
        spies["codex"].assert_not_awaited()
        spies["fail"].assert_not_awaited()

    def test_author_enabled_by_default_and_disabled_for_explicit_fallbacks(self) -> None:
        from backend.generation.study_materials.orchestrator import _study_materials_author_enabled

        with patch.dict("os.environ", {}, clear=False) as environ:
            environ.pop("STUDY_MATERIALS_AGENT_RUNTIME", None)
            self.assertTrue(_study_materials_author_enabled())
        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "author"}, clear=False):
            self.assertTrue(_study_materials_author_enabled())
        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "legacy"}, clear=False):
            self.assertFalse(_study_materials_author_enabled())
        with patch.dict("os.environ", {"STUDY_MATERIALS_AGENT_RUNTIME": "codex_runtime"}, clear=False):
            self.assertFalse(_study_materials_author_enabled())


class _SearchAgent(WebSearchKnowledgeToolsMixin):
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            reflector_model="reflector-test",
            summarizer_model="summarizer-test",
            planner_model="planner-test",
        )
        self.llm_calls: list[dict] = []

    def _strict_llm(self, _ctx: CompressedContext, args: dict) -> bool:
        return bool(args.get("strict_llm"))

    async def _call_llm_text(self, **kwargs):
        self.llm_calls.append(kwargs)
        return json.dumps({"sub_questions": ["导数的定义是什么？"]}, ensure_ascii=False)

    def _extract_json_obj(self, text: str) -> dict:
        try:
            obj = json.loads(text)
        except (TypeError, ValueError):
            return {}
        return obj if isinstance(obj, dict) else {}


class WebSearchDecomposeDefaultTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        web_impl._TASK_HEALTH_FALLBACK.clear()

    async def test_decompose_defaults_off_when_env_unset(self) -> None:
        agent = _SearchAgent()
        ctx = CompressedContext(
            user_profile=UserProfile(user_id="u", preferences={"subject": "高中数学"}),
            system_instructions="",
            current_task="高中数学 复习",
        )
        tavily_search = AsyncMock(
            return_value={
                "success": True,
                "provider": "tavily",
                "query": "q",
                "results": [{"title": "导数定义", "url": "https://example.com/deriv", "snippet": "导数表示瞬时变化率。"}],
            }
        )

        with patch.dict("os.environ", {"STUDY_MATERIALS_SEARCH_MODE": "", "STUDY_MATERIALS_PRESET": ""}, clear=False) as environ:
            environ.pop("STUDY_MATERIALS_WEB_DECOMPOSE", None)
            with patch(
                "backend.agent.tools.search.web_search_knowledge_impl.is_llm_configured",
                return_value=True,
            ), patch("backend.integrations.mcp.search.tavily.TAVILY_API_KEY", "tvly-test"), patch(
                "backend.integrations.mcp.search.tavily.tavily_search", tavily_search
            ):
                result = await agent._tool_web_search_knowledge(
                    {"knowledge_points": ["导数"], "disable_metaso": True, "limit": 5},
                    ctx,
                )

        item = result["items"][0]
        self.assertEqual(item["provider"], "tavily-search")
        self.assertTrue(item["results"])
        # decompose 默认关闭：不再为子问题拆分调用 LLM。
        self.assertEqual(agent.llm_calls, [])


class AuthorEventForwardingDrainTests(unittest.IsolatedAsyncioTestCase):
    """I-5：author 事件转发须在终端迁移（done / fail_task）前 drain，取消后不留泄露 task。"""

    @staticmethod
    def _success_result() -> dict:
        return {
            "success": True,
            "markdown": "# 函数单调性",
            "material": {"iteration": 1, "markdown": "# 函数单调性", "passed": True},
            "acceptance": {},
            "quality_report": {},
            "review": {},
            "plan": {},
            "research": {},
            "coverage_map": {},
            "sections": [{"title": "单调性的定义"}],
            "revision_attempts": 0,
            "todos": [],
            "references": [],
            "audit": {},
            "quality_notes": [],
            "blueprint": {},
            "degraded": False,
        }

    @staticmethod
    def _slow_recorder(recorded: list, *, slow_s: float = 0.05):
        """慢 append 记录器：非 done 事件故意慢于 done，未 drain 时 done 会先落（复现竞态）。"""

        async def _append(task, event):
            if event.get("event") != "done":
                await asyncio.sleep(slow_s)
            recorded.append(event)

        return _append

    def _common_patches(self, manager, orchestrator, recorded: list, *, fail_mock: AsyncMock | None = None):
        return (
            patch.object(orchestrator.task_runtime, "append_event", new=self._slow_recorder(recorded)),
            patch.object(orchestrator.task_runtime, "complete_task", new=AsyncMock()),
            patch.object(orchestrator.task_runtime, "fail_task", new=fail_mock or AsyncMock()),
            patch.object(manager, "_upsert_archive_from_resume_state", new=AsyncMock()),
            patch.object(manager, "_persist_snapshot"),
        )

    async def test_author_events_all_land_before_done(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task(task_id="study-author-drain-done")
        ctx = manager._task_run_context(task)
        recorded: list = []

        async def _fake_pipeline(pipeline_ctx, *, llm_func, toolbox, emit, forge):
            for idx in range(3):
                emit({"event": "author_progress", "data": {"idx": idx}})
            await asyncio.sleep(0)  # 让转发任务启动并进入慢 append
            return self._success_result()

        patches = self._common_patches(manager, orchestrator, recorded)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch.object(
            orchestrator, "run_author_pipeline", new=_fake_pipeline
        ):
            await manager._run_author_staged(ctx)
            await asyncio.sleep(0.2)  # 放任任何迟到转发落定后再断言

        kinds = [evt.get("event") for evt in recorded]
        self.assertEqual(kinds, ["author_progress", "author_progress", "author_progress", "done"])
        # 同序转发：转发落盘顺序与 emit 顺序一致。
        self.assertEqual([evt["data"]["idx"] for evt in recorded[:3]], [0, 1, 2])

    async def test_author_events_all_land_before_fail_task(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task(task_id="study-author-drain-fail")
        ctx = manager._task_run_context(task)
        recorded: list = []

        async def _record_fail(*args, **kwargs):
            recorded.append({"event": "__fail__", "error": kwargs.get("error")})

        async def _fake_pipeline(pipeline_ctx, *, llm_func, toolbox, emit, forge):
            for idx in range(2):
                emit({"event": "author_progress", "data": {"idx": idx}})
            await asyncio.sleep(0)
            return {
                "success": False,
                "error": {
                    "code": "author_audit_failed",
                    "stage": "audit",
                    "issues": ["x"],
                    "detail": "frontier section audit timed out",
                },
            }

        patches = self._common_patches(manager, orchestrator, recorded, fail_mock=AsyncMock(side_effect=_record_fail))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch.object(
            orchestrator, "run_author_pipeline", new=_fake_pipeline
        ):
            await manager._run_author_staged(ctx)
            await asyncio.sleep(0.2)

        kinds = [evt.get("event") for evt in recorded]
        self.assertEqual(kinds, ["author_progress", "author_progress", "__fail__"])
        self.assertEqual(recorded[-1]["error"]["detail"], "frontier section audit timed out")

    async def test_author_emit_cancel_leaves_no_pending_forward_tasks(self) -> None:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task(task_id="study-author-drain-cancel")
        ctx = manager._task_run_context(task)
        recorded: list = []

        async def _fake_pipeline(pipeline_ctx, *, llm_func, toolbox, emit, forge):
            emit({"event": "author_progress", "data": {"idx": 0}})
            await asyncio.sleep(0.02)  # 第一个事件的转发仍在进行中
            task.status = "canceled"  # 模拟用户取消
            emit({"event": "author_progress", "data": {"idx": 1}})  # _author_emit 同步抛 CancelledError

        before = asyncio.all_tasks()
        patches = self._common_patches(manager, orchestrator, recorded)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch.object(
            orchestrator, "run_author_pipeline", new=_fake_pipeline
        ):
            with self.assertRaises(asyncio.CancelledError):
                await manager._run_author_staged(ctx)

        leaked = [t for t in asyncio.all_tasks() - before if not t.done()]
        self.assertEqual(leaked, [])


class AuthorDonePayloadSlimTests(unittest.IsolatedAsyncioTestCase):
    """done 载荷瘦身：DB JSON 截断线（TASK_JSON_MAX_CHARS=200k）以下留余量，正文/acceptance 不动。"""

    @staticmethod
    def _big_success_result() -> dict:
        markdown = "# 成稿\n" + "正文段落。" * 13000  # ~65k，deep 档典型体量
        blueprint = {
            "narrative": "叙事主线。" * 2000,
            "terminology": [{"symbol": f"s{i}", "meaning": "术语含义。" * 20} for i in range(40)],
            "sections": [
                {
                    "id": f"sec-{i}",
                    "title": f"第 {i} 节",
                    "purpose": "写作目的。" * 100,
                    "key_points": ["要点。" * 50],
                    "target_chars": 2000,
                    "difficulty": "standard",
                    "misconceptions": [],
                    "frontier": False,
                }
                for i in range(1, 13)
            ],
            "figures": [
                {"n": i, "sec_id": "sec-1", "intent": "示意图", "kind": "mermaid", "caption": "图"}
                for i in range(1, 4)
            ],
        }
        return {
            "success": True,
            "markdown": markdown,
            "material": {"iteration": 1, "markdown": markdown, "passed": True, "issues": []},
            "acceptance": {"status": "accepted", "checks": ["placeholder_free"]},
            "quality_report": {"passed": True, "failed_checks": [], "issues": []},
            "review": {"passed": True, "draft_hash": "h", "dimensions": {}, "issues": []},
            "plan": {"knowledge_points": [{"id": "kp-1", "title": "单调性"}]},
            "research": {
                "kp-1": [
                    {"url": f"https://example.com/{i}", "title": "证据", "snippet": "证据摘要。" * 100}
                    for i in range(80)
                ]
            },
            "coverage_map": {"kp-1": True},
            "sections": [{"title": "单调性的定义"}],
            "revision_attempts": 0,
            "todos": [],
            "references": [],
            "audit": {"frontier_sections": [], "unsupported": [], "passed": True},
            "quality_notes": [],
            "blueprint": blueprint,
            "degraded": False,
        }

    async def _capture_done(self, pipeline_result: dict) -> tuple[dict, dict]:
        from backend.generation.study_materials import orchestrator

        manager = StudyMaterialsTaskManager()
        task = _task(task_id="study-author-slim")
        ctx = manager._task_run_context(task)
        recorded: list = []
        complete = AsyncMock()

        async def _append(_task, event):
            recorded.append(event)

        async def _fake_pipeline(pipeline_ctx, *, llm_func, toolbox, emit, forge):
            return pipeline_result

        with patch.object(orchestrator.task_runtime, "append_event", new=_append), patch.object(
            orchestrator.task_runtime, "complete_task", new=complete
        ), patch.object(orchestrator.task_runtime, "fail_task", new=AsyncMock()), patch.object(
            manager, "_upsert_archive_from_resume_state", new=AsyncMock()
        ), patch.object(manager, "_persist_snapshot"), patch.object(
            orchestrator, "run_author_pipeline", new=_fake_pipeline
        ):
            await manager._run_author_staged(ctx)

        done_events = [evt for evt in recorded if evt.get("event") == "done"]
        self.assertEqual(len(done_events), 1)
        done_data = done_events[0]["data"]
        complete_result = complete.call_args.kwargs["result"]
        return done_data, complete_result

    async def test_done_payload_stays_under_db_cap_with_large_markdown(self) -> None:
        result = self._big_success_result()
        markdown = result["markdown"]

        done_data, complete_result = await self._capture_done(result)

        payload_chars = len(json.dumps(done_data, ensure_ascii=False))
        self.assertLess(payload_chars, 150_000)  # 200k 截断线以下留余量
        self.assertEqual(complete_result, done_data)  # done 事件与 complete_task 结果同一份
        self.assertTrue(done_data["success"])
        self.assertEqual(done_data["material"]["markdown"], markdown)  # 正文完整保留
        self.assertEqual(done_data["acceptance"], {"status": "accepted", "checks": ["placeholder_free"]})

    async def test_author_blueprint_is_slimmed_to_summary(self) -> None:
        done_data, _ = await self._capture_done(self._big_success_result())

        self.assertEqual(
            done_data["author"]["blueprint"],
            {
                "sections": [{"id": f"sec-{i}", "title": f"第 {i} 节"} for i in range(1, 13)],
                "figures": 3,
            },
        )

    async def test_done_workflow_drops_heavy_duplicates_and_cold_resume_backfills_markdown(self) -> None:
        result = self._big_success_result()
        markdown = result["markdown"]
        acceptance = result["acceptance"]

        done_data, _ = await self._capture_done(result)
        workflow = done_data["workflow"]
        self.assertNotIn("markdown", workflow)  # 不再重复携带整份正文
        self.assertEqual(workflow.get("research"), {})  # 证据全文不进 done 载荷
        self.assertEqual(workflow.get("research_evidence_count"), 80)
        self.assertEqual(workflow["acceptance"], acceptance)  # fix_export 续作仍要校验验收
        self.assertEqual(workflow["plan"], result["plan"])

        # B3 冷续作：从瘦身后的 done 载荷重建 resume wm 时，material.markdown 回填进 workflow。
        from backend.generation.study_materials.orchestrator import _resume_wm_from_result_payload

        wm = _resume_wm_from_result_payload(
            done_data, query="函数单调性", subject="高中数学", options={"preset": "standard"}
        )
        restored = wm["study_materials_workflow"]
        self.assertEqual(restored["markdown"], markdown)
        self.assertEqual(restored["acceptance"], acceptance)


if __name__ == "__main__":
    unittest.main()
