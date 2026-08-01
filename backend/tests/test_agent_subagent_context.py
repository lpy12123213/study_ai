import asyncio
import os
import unittest
from unittest.mock import patch


class TestAgentSubagentContext(unittest.TestCase):
    def test_context_compressor_prompt_uses_registry(self) -> None:
        from backend.agent.config import AgentConfig
        from backend.agent.context import ContextManager
        from backend.llm.prompts import create_default_prompt_registry

        captured = {}

        async def fake_chat_completion_text(**kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = kwargs["messages"]
            return "用户要生成导数资料；已完成检索。"

        manager = ContextManager(config=AgentConfig(summarizer_model="dummy-model"))

        with patch("backend.agent.context.chat_completion_text", new=fake_chat_completion_text):
            text = asyncio.run(manager._summarize_messages([{"role": "user", "content": "生成导数资料"}]))

        self.assertIn("导数", text)
        self.assertEqual(
            captured["messages"][0]["content"],
            create_default_prompt_registry().render("agent.context.compress.v1").content,
        )

    def test_reflector_prompt_uses_registry(self) -> None:
        from backend.agent import reflector
        from backend.llm.prompts import create_default_prompt_registry

        self.assertEqual(
            reflector._reflector_system_prompt(),
            create_default_prompt_registry().render("agent.reflector.study_materials.v1").content,
        )

    def test_collect_completed_overview(self) -> None:
        from backend.agent.tools.knowledge import study_material_generation as smg
        from backend.agent.types import CompressedContext, UserProfile

        ctx = CompressedContext(user_profile=UserProfile(user_id="u"), system_instructions="", current_task="t")
        ctx.working_memory["generate_study_material"] = {
            "sections": [
                {
                    "knowledge_point": "KP-A",
                    "explanation_markdown": "#### 标题A\n\n这里是 A 的讲解内容，包含一些定义与性质。",
                }
            ]
        }
        ctx.working_memory["subagent_summaries"] = {"KP-B": "B 的摘要（来自 subagent）。"}

        local_sections = [
            {"knowledge_point": "KP-C", "explanation_markdown": "#### 标题C\n\nC 的讲解。"},
        ]

        res = smg._collect_completed_overview(ctx, current_kp="KP-D", local_sections=local_sections, limit=8)
        kps = [x.get("knowledge_point") for x in res]
        self.assertIn("KP-A", kps)
        self.assertIn("KP-B", kps)
        self.assertIn("KP-C", kps)

        # Ensure headings are stripped from the summary excerpt.
        for it in res:
            summary = str(it.get("summary") or "")
            self.assertNotIn("####", summary)

    def test_collect_completed_overview_excludes_current(self) -> None:
        from backend.agent.tools.knowledge import study_material_generation as smg
        from backend.agent.types import CompressedContext, UserProfile

        ctx = CompressedContext(user_profile=UserProfile(user_id="u"), system_instructions="", current_task="t")
        ctx.working_memory["generate_study_material"] = {
            "sections": [
                {
                    "knowledge_point": "KP-A",
                    "explanation_markdown": "#### A\n\n内容",
                }
            ]
        }

        res = smg._collect_completed_overview(ctx, current_kp="KP-A", local_sections=[], limit=8)
        self.assertEqual(res, [])

    def test_set_plan_summary(self) -> None:
        from backend.agent.core import AgentCore
        from backend.agent.types import CompressedContext, ExecutionPlan, PlanStep, UserProfile

        agent = AgentCore()
        profile = UserProfile(user_id="u", preferences={"subject": "高中数学"})
        ctx = CompressedContext(user_profile=profile, system_instructions="", current_task="t")
        ctx.working_memory["study_options"] = {"preset": "deep", "requirements": "R" * 2000}
        ctx.working_memory["split_knowledge_points"] = {"knowledge_points": ["A", "B", "C"]}

        plan = ExecutionPlan(topic="t", steps=[PlanStep(id="s1", title="x", tool="noop")], rationale="why")
        agent._set_plan_summary(ctx=ctx, topic="t", profile=profile, plan=plan, export_only=False)

        ps = ctx.working_memory.get("plan_summary") or {}
        self.assertEqual(ps.get("subject"), "高中数学")
        self.assertEqual(ps.get("preset"), "deep")
        self.assertEqual(ps.get("knowledge_points"), ["A", "B", "C"])
        self.assertTrue(isinstance(ps.get("requirements"), str))
        self.assertLessEqual(len(ps.get("requirements") or ""), 900)

    def test_summarize_subagent_fallback(self) -> None:
        from backend.agent.config import AgentConfig
        from backend.agent.core import AgentCore
        from backend.agent.types import CompressedContext, UserProfile

        # Force the "no LLM" path for deterministic tests regardless of local .env keys.
        os.environ.pop("LESSON_PLAN_API_KEY", None)
        os.environ.pop("MOONSHOT_API_KEY", None)
        agent = AgentCore(config=AgentConfig(planner_model="", summarizer_model="", reflector_model=""))
        ctx = CompressedContext(user_profile=UserProfile(user_id="u"), system_instructions="", current_task="t")
        ctx.working_memory["generate_study_material"] = {
            "sections": [
                {
                    "knowledge_point": "KP-A",
                    "explanation_markdown": "#### 标题A\n\n这里是 A 的讲解内容。",
                }
            ]
        }

        text = asyncio.run(agent._summarize_subagent(ctx=ctx, kp="KP-A"))
        self.assertTrue(isinstance(text, str))
        self.assertTrue(text.strip())
        self.assertNotIn("####", text)

    def test_normalize_event_payload_preserves_subagent_fields(self) -> None:
        from backend.shared.tasks.runtime import TaskRuntime

        runtime = TaskRuntime.__new__(TaskRuntime)
        payload = runtime._normalize_event_payload(
            task_id="task-1",
            event={
                "event": "subagent_start",
                "data": {
                    "subagent_id": "sa-0",
                    "index": 0,
                    "total": 3,
                    "kind": "knowledge_research",
                    "knowledge_point": "函数",
                    "content": "启动",
                },
            },
        )

        self.assertEqual(payload["type"], "subagent_start")
        d = payload["data"]
        self.assertEqual(d["subagent_id"], "sa-0")
        self.assertEqual(d["index"], 0)
        self.assertEqual(d["total"], 3)
        self.assertEqual(d["kind"], "knowledge_research")
        self.assertEqual(d["knowledge_point"], "函数")
        self.assertEqual(d["content"], "启动")

    def test_compact_catchup_events_retains_subagent_and_tool_events(self) -> None:
        from backend.generation.study_materials import orchestrator as orch

        events = [
            {"type": "status", "data": {"content": "s1"}},
            {"type": "subagent_start", "data": {"subagent_id": "sa-0", "kind": "knowledge_research"}},
            {"type": "status", "data": {"content": "s2"}},
            {"type": "tool_result", "data": {"subagent_id": "sa-0", "step_id": "x"}},
            {"type": "subagent_end", "data": {"subagent_id": "sa-0"}},
            {"type": "status", "data": {"content": "s3"}},
            {"type": "thinking", "data": {"content": "t1"}},
        ]

        compacted, skipped = orch._compact_catchup_events(events)
        types = [e["type"] for e in compacted]

        # 状态演进类（subagent_*/tool_*）全量保留；仅折叠 status/thinking。
        self.assertEqual(types.count("subagent_start"), 1)
        self.assertEqual(types.count("subagent_end"), 1)
        self.assertEqual(types.count("tool_result"), 1)
        self.assertEqual(types.count("status"), 1)
        self.assertEqual(types.count("thinking"), 1)
        self.assertEqual(skipped, 2)
        # 保留的 status 是最新一条，整体顺序保持。
        self.assertEqual([e for e in compacted if e["type"] == "status"][0]["data"]["content"], "s3")
        self.assertEqual(compacted[-1]["type"], "thinking")

    def test_export_subagent_events_tagged(self) -> None:
        from backend.agent.core import AgentCore
        from backend.agent.types import CompressedContext, UserProfile

        agent = AgentCore.__new__(AgentCore)
        ctx = CompressedContext(user_profile=UserProfile(user_id="u"), system_instructions="", current_task="t")

        async def _collect() -> tuple:
            starts = [e async for e in agent._start_export_subagent(ctx=ctx, kp="导出：LaTeX/PDF")]
            ends = [e async for e in agent._end_export_subagent(ctx=ctx, kp="导出：LaTeX/PDF", content="done")]
            return starts, ends

        starts, ends = asyncio.run(_collect())
        start_evt = next(e for e in starts if e.get("event") == "subagent_start")
        end_evt = next(e for e in ends if e.get("event") == "subagent_end")
        self.assertEqual(start_evt["data"]["subagent_id"], "sa-export")
        self.assertEqual(start_evt["data"]["kind"], "export")
        self.assertEqual(start_evt["data"]["knowledge_point"], "导出：LaTeX/PDF")
        self.assertEqual(end_evt["data"]["subagent_id"], "sa-export")
        self.assertEqual(end_evt["data"]["kind"], "export")
        self.assertEqual(end_evt["data"]["content"], "done")


if __name__ == "__main__":
    unittest.main()
