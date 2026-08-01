"""写作链路两个线上缺陷的回归测试：

1. `generate_study_material` 的步骤超时预算（此前 240s，deep preset 实测连续 14 次硬超时）。
2. 写作工具在无 aggregate/synthesize 时从检索工作记忆回退建素材，0 素材时诚实报错
   （此前静默返回空 sections，实测 ReAct 连续 21 次 6ms 空调用产出空壳档案）。
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.agent.executor import Executor
from backend.agent.tools.analysis.content_review import ContentReviewToolsMixin
from backend.agent.tools.knowledge.study_material_generation import (
    StudyMaterialGenerationToolsMixin,
    _items_from_search_memory,
)
from backend.agent.types import ActionResults, CompressedContext, PlanStep, StepResult, UserProfile


class _DummyAgent(StudyMaterialGenerationToolsMixin):
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            reflector_model="reflector-test",
            summarizer_model="summarizer-test",
            planner_model="planner-test",
        )

    def _strict_llm(self, _ctx: CompressedContext, args: dict) -> bool:
        return bool(args.get("strict_llm"))

    async def _call_llm_text(self, **_kwargs):  # pragma: no cover
        raise AssertionError("LLM should not be called in fallback unit tests")

    async def _call_llm_markdown_with_continuation(self, **_kwargs):  # pragma: no cover
        raise AssertionError("LLM should not be called in fallback unit tests")

    def _extract_json_obj(self, _text: str) -> dict:
        raise AssertionError("JSON extraction should not be needed in fallback unit tests")


def _make_ctx(*, task: str = "TCP 拥塞控制", subject: str = "计算机网络") -> CompressedContext:
    return CompressedContext(
        user_profile=UserProfile(user_id="u", preferences={"subject": subject}),
        system_instructions="",
        current_task=task,
    )


def _search_wm() -> dict:
    return {
        "web_search_knowledge": {
            "topic": "TCP 拥塞控制",
            "items": [
                {
                    "knowledge_point": "慢启动",
                    "provider": "exa-search+decompose",
                    "query": "TCP 慢启动",
                    "scope": "webpage",
                    "results": [{"title": "慢启动 - 维基百科", "url": "https://example.test/slow-start", "snippet": "慢启动每 RTT 翻倍"}],
                },
                {
                    "knowledge_point": "拥塞避免",
                    "provider": "exa-search+decompose",
                    "query": "TCP 拥塞避免",
                    "scope": "webpage",
                    "results": [{"title": "拥塞避免", "url": "https://example.test/ca", "snippet": "线性增长"}],
                },
            ],
        },
        "wikipedia_search": {
            "items": [
                {
                    "knowledge_point": "慢启动",
                    "success": True,
                    "title": "TCP 拥塞控制",
                    "url": "https://zh.wikipedia.org/wiki/TCP",
                    "summary": "慢启动是 TCP 拥塞控制的初始阶段。",
                    "content": "慢启动阶段拥塞窗口指数增长。",
                }
            ]
        },
    }


class WriteStepTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def _capture_timeout(self, env: dict, *, unset_write_env: bool = False) -> float:
        captured: dict = {}

        async def fake_wait_for(coro, timeout):  # noqa: ANN001
            captured["timeout"] = timeout
            coro.close()
            return {"ok": True}

        executor = Executor()

        async def _stub(args, context):  # noqa: ANN001, ARG001
            return {"sections": []}

        executor._tool_handlers["generate_study_material"] = _stub
        step = PlanStep(id="s1", title="写作", tool="generate_study_material", arguments={})
        ctx = _make_ctx()
        with patch.dict(os.environ, env, clear=False):
            if unset_write_env:
                os.environ.pop("STUDY_MATERIALS_WRITE_STEP_TIMEOUT_S", None)
            with patch("asyncio.wait_for", fake_wait_for):
                result = await executor.execute_step(step, context=ctx)
        self.assertTrue(result.success)
        return float(captured["timeout"])

    async def test_generate_study_material_gets_long_default_budget(self) -> None:
        timeout = await self._capture_timeout({"STUDY_MATERIALS_STEP_TIMEOUT_S": "240"}, unset_write_env=True)
        # 默认 20min，且不被通用 240s 预算压低。
        self.assertGreaterEqual(timeout, 60.0 * 20.0)

    async def test_write_timeout_env_override_respected(self) -> None:
        timeout = await self._capture_timeout(
            {"STUDY_MATERIALS_STEP_TIMEOUT_S": "240", "STUDY_MATERIALS_WRITE_STEP_TIMEOUT_S": "600"}
        )
        self.assertEqual(timeout, 600.0)

    async def test_write_timeout_env_clamped_to_minimum(self) -> None:
        timeout = await self._capture_timeout(
            {"STUDY_MATERIALS_STEP_TIMEOUT_S": "240", "STUDY_MATERIALS_WRITE_STEP_TIMEOUT_S": "60"}
        )
        self.assertEqual(timeout, 300.0)


class SearchMemoryFallbackTests(unittest.TestCase):
    def test_items_from_search_memory_merges_per_kp(self) -> None:
        ctx = _make_ctx()
        ctx.working_memory.update(_search_wm())
        items = _items_from_search_memory(ctx)
        by_kp = {str(i.get("knowledge_point")): i for i in items}
        self.assertEqual(set(by_kp), {"慢启动", "拥塞避免"})
        self.assertEqual(by_kp["慢启动"]["web_search"]["provider"], "exa-search+decompose")
        self.assertEqual(by_kp["慢启动"]["wikipedia"]["url"], "https://zh.wikipedia.org/wiki/TCP")
        self.assertNotIn("wikipedia", by_kp["拥塞避免"])

    def test_items_from_search_memory_ignores_malformed(self) -> None:
        ctx = _make_ctx()
        ctx.working_memory["web_search_knowledge"] = {"items": ["bad", {"no_kp": 1}, None]}
        self.assertEqual(_items_from_search_memory(ctx), [])


class GenerateWithSearchMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_uses_search_memory_when_no_aggregate(self) -> None:
        agent = _DummyAgent()
        ctx = _make_ctx()
        ctx.working_memory.update(_search_wm())
        with patch(
            "backend.agent.tools.knowledge.study_material_generation.is_llm_configured",
            return_value=False,
        ):
            result = await agent._tool_generate_study_material({"knowledge_points": ["慢启动"]}, ctx)
        self.assertEqual(len(result["sections"]), 1)
        self.assertEqual(result["sections"][0]["knowledge_point"], "慢启动")
        self.assertTrue(result["sections"][0]["explanation_markdown"].strip())

    async def test_requested_filter_applies_after_search_memory_fallback(self) -> None:
        agent = _DummyAgent()
        ctx = _make_ctx()
        ctx.working_memory.update(_search_wm())
        with patch(
            "backend.agent.tools.knowledge.study_material_generation.is_llm_configured",
            return_value=False,
        ):
            result = await agent._tool_generate_study_material({"knowledge_points": ["拥塞避免"]}, ctx)
        self.assertEqual([s["knowledge_point"] for s in result["sections"]], ["拥塞避免"])

    async def test_generate_raises_without_any_research(self) -> None:
        agent = _DummyAgent()
        ctx = _make_ctx()
        with patch(
            "backend.agent.tools.knowledge.study_material_generation.is_llm_configured",
            return_value=False,
        ):
            with self.assertRaises(RuntimeError) as cm:
                await agent._tool_generate_study_material({"knowledge_points": ["慢启动"]}, ctx)
        self.assertIn("缺少可用检索素材", str(cm.exception))


class _FlakyReviewAgent(_DummyAgent):
    """审阅调用按脚本返回（用于 invalid_json 重试/回退测试）。"""

    def __init__(self, review_outputs: list[str]) -> None:
        super().__init__()
        self._review_outputs = list(review_outputs)
        self.review_calls = 0

    async def _call_llm_markdown_with_continuation(self, **_kwargs):
        return {"content": "慢启动每 RTT 窗口翻倍。", "finish_reason": "stop"}

    async def _call_llm_text(self, **_kwargs):
        self.review_calls += 1
        if self._review_outputs:
            return self._review_outputs.pop(0)
        return '{"passed": true, "issues": [], "suggestions": []}'

    def _extract_json_obj(self, text: str) -> dict:
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {}
        return obj if isinstance(obj, dict) else {}


class ReviewInvalidJsonTests(unittest.IsolatedAsyncioTestCase):
    async def _run_with_review_outputs(self, outputs: list[str]) -> dict:
        agent = _FlakyReviewAgent(outputs)
        ctx = _make_ctx()
        ctx.working_memory.update(_search_wm())
        with patch(
            "backend.agent.tools.knowledge.study_material_generation.is_llm_configured",
            return_value=True,
        ):
            result = await agent._tool_generate_study_material(
                {"knowledge_points": ["慢启动"], "strict_llm": True}, ctx
            )
        return agent, result["sections"][0]["writer_agent"]["review"]

    async def test_invalid_json_review_retries_once_then_succeeds(self) -> None:
        agent, review = await self._run_with_review_outputs(
            ["这不是 JSON", '{"passed": true, "issues": [], "suggestions": []}']
        )
        self.assertEqual(agent.review_calls, 2)
        self.assertEqual(review["source"], "llm")
        self.assertTrue(review["passed"])

    async def test_invalid_json_review_falls_back_without_raise_even_strict(self) -> None:
        agent, review = await self._run_with_review_outputs(["垃圾输出", "仍然不是 JSON"])
        self.assertEqual(agent.review_calls, 2)
        self.assertEqual(review["source"], "invalid_json_fallback")
        self.assertTrue(review["passed"])


class StepFailurePolicyTests(unittest.IsolatedAsyncioTestCase):
    async def _handle_failure(self, tool: str) -> CompressedContext:
        from backend.agent.streaming.events import maybe_handle_step_failure

        ctx = _make_ctx()
        results = ActionResults()
        step = PlanStep(id="s1", title=tool, tool=tool, arguments={})
        result = StepResult(step_id="s1", tool=tool, success=False, error="boom")

        async def _noop_execute(**_kwargs):  # pragma: no cover
            return
            yield  # make it an async generator

        async for _evt in maybe_handle_step_failure(
            ctx=ctx,
            results=results,
            concrete_step=step,
            step_result=result,
            execute_concrete_step=_noop_execute,
        ):
            pass
        return ctx

    async def test_generate_study_material_failure_is_not_fatal(self) -> None:
        ctx = await self._handle_failure("generate_study_material")
        self.assertNotIn("_abort_execution", ctx.working_memory)

    async def test_split_knowledge_points_failure_still_fatal(self) -> None:
        ctx = await self._handle_failure("split_knowledge_points")
        self.assertTrue(ctx.working_memory.get("_abort_execution"))


class DoneMaterialPayloadTests(unittest.IsolatedAsyncioTestCase):
    """done.material.markdown 契约：真稿必须随 done 下发（orchestrator 据此判 completed），
    空时保持空串（维持 empty_material 诚实失败）。"""

    async def _collect_done_material(self, *, with_markdown: bool) -> dict:
        import tempfile

        from backend.agent.config import AgentConfig
        from backend.agent.context import ContextManager
        from backend.agent.core import AgentCore
        from backend.agent.mcp.registry import MCPToolRegistry
        from backend.agent.memory import MemoryStore
        from backend.agent.memory.semantic_store import SemanticStore

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = AgentConfig(agent_mode="react", planner_model="test-model", reflector_model="", summarizer_model="")

        class _FakeExecutor:
            def __init__(self) -> None:
                self.tool_registry = MCPToolRegistry()

            async def execute_step(self, step, *, context, emit_event=None):  # noqa: ANN001
                from backend.agent.types import StepResult

                return StepResult(step_id=step.id, tool=step.tool, success=True, output={"ok": True})

        agent = AgentCore(
            config=config,
            memory_store=MemoryStore(storage_path=str(Path(tmp.name) / "profiles.json")),
            semantic_store=SemanticStore(persist_dir=str(Path(tmp.name) / "semantic")),
            context_manager=ContextManager(config=config),
            executor=_FakeExecutor(),  # type: ignore[arg-type]
        )

        class _FakeLoop:
            def __init__(self, config, tool_registry):  # noqa: ANN001, ARG002
                pass

            async def run(self, **kwargs):  # noqa: ANN003
                ctx = kwargs["ctx"]
                if with_markdown:
                    ctx.working_memory["markdown"] = "# 自学材料：真稿\n\n正文内容。"
                ctx.working_memory["review_content"] = {"passed": True, "issues": [], "suggestions": []}
                return
                yield  # pragma: no cover - async generator shape

        with (
            patch("backend.agent.core.ReActLoop", _FakeLoop),
            patch("backend.agent.core.is_llm_configured", return_value=True),
            patch.object(agent, "_schedule_semantic_upsert", lambda **kwargs: None),
        ):
            events = []
            async for evt in agent.run("测试主题", user_id="u", preferences={"subject": "数学"}, options={"preset": "standard"}):
                events.append(evt)
        done = [e for e in events if isinstance(e, dict) and e.get("event") == "done"]
        self.assertTrue(done, "run 应产出 done 事件")
        return done[-1].get("data", {}).get("material", {})

    async def test_done_material_carries_real_markdown(self) -> None:
        material = await self._collect_done_material(with_markdown=True)
        self.assertEqual(material.get("markdown"), "# 自学材料：真稿\n\n正文内容。")

    async def test_done_material_markdown_stays_empty_when_nothing_written(self) -> None:
        material = await self._collect_done_material(with_markdown=False)
        self.assertEqual(str(material.get("markdown") or ""), "")


class ReviseMarkdownShrinkGuardTests(unittest.IsolatedAsyncioTestCase):
    """revise_markdown 长度护栏：截断/过度压缩的修订稿不得覆盖完整档案。"""

    class _ReviseAgent(ContentReviewToolsMixin):
        def __init__(self, revised: str) -> None:
            self.config = SimpleNamespace(planner_model="test-model")
            self._revised = revised
            self.last_max_tokens = 0

        def _strict_llm(self, _ctx, _args) -> bool:  # noqa: ANN001
            return False

        async def _call_llm_text(self, **kwargs):  # noqa: ANN003
            self.last_max_tokens = int(kwargs.get("max_tokens") or 0)
            return self._revised

    def _ctx_with_doc(self, chars: int) -> CompressedContext:
        ctx = _make_ctx()
        ctx.working_memory["markdown"] = "# 自学材料\n\n" + ("正文段落。" * (chars // 5))
        return ctx

    async def test_suspicious_shrink_rejected_keeps_original(self) -> None:
        original_len = len(self._ctx_with_doc(2000).working_memory["markdown"])
        agent = self._ReviseAgent("# 自学材料\n\n只剩一小段。")
        ctx = self._ctx_with_doc(2000)
        with patch("backend.agent.tools.analysis.content_review.is_llm_configured", return_value=True):
            result = await agent._tool_revise_markdown({}, ctx)
        self.assertEqual(len(result), original_len)
        self.assertEqual(len(ctx.working_memory["markdown"]), original_len)

    async def test_normal_revision_accepted_and_budget_scales(self) -> None:
        ctx = self._ctx_with_doc(2000)
        original_len = len(ctx.working_memory["markdown"])
        revised_text = ctx.working_memory["markdown"] + "\n\n补充：适用条件说明。"
        agent = self._ReviseAgent(revised_text)
        with patch("backend.agent.tools.analysis.content_review.is_llm_configured", return_value=True):
            result = await agent._tool_revise_markdown({}, ctx)
        self.assertEqual(result, revised_text)
        self.assertGreaterEqual(agent.last_max_tokens, 8000)
        self.assertGreaterEqual(agent.last_max_tokens, int(original_len * 1.6))


if __name__ == "__main__":
    unittest.main()
