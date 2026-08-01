"""T15 运行时收敛回归：author 为默认 runtime，decompose 默认关闭。

覆盖：
- ``STUDY_MATERIALS_AGENT_RUNTIME`` 未设置时 ``_run_task`` dispatch 到 author 流水线；
- 显式设 ``legacy`` 时仍走 legacy AgentCore 路径；
- ``STUDY_MATERIALS_WEB_DECOMPOSE`` 未设置且未显式传参时不再做子问题拆分。
"""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
