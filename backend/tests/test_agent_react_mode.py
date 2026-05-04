import os
import unittest


class _FakeExecutor:
    def __init__(self, tool_registry) -> None:
        self.tool_registry = tool_registry
        self.calls = []

    async def execute_step(self, step, *, context, emit_event=None):  # type: ignore[override]
        from backend.agent.types import StepResult

        self.calls.append(step.tool)

        if step.tool == "split_knowledge_points":
            return StepResult(
                step_id=step.id,
                tool=step.tool,
                success=True,
                output={"knowledge_points": ["KP-1", "KP-2"]},
            )

        if step.tool == "assemble_study_archive":
            # Mimic the real tool: it writes markdown into working_memory.
            context.working_memory["markdown"] = "# 自学材料：测试\n\nOK\n"
            return StepResult(
                step_id=step.id,
                tool=step.tool,
                success=True,
                output={"topic": context.current_task, "markdown_chars": len(context.working_memory["markdown"])},
            )

        if step.tool == "save_markdown_file":
            # Avoid filesystem writes in unit tests.
            context.working_memory["archive_path"] = "dummy.md"
            return StepResult(
                step_id=step.id,
                tool=step.tool,
                success=True,
                output={"success": True, "path": "dummy.md"},
            )

        if step.tool == "review_content":
            context.working_memory["review_content"] = {"passed": True, "issues": [], "suggestions": []}
            return StepResult(
                step_id=step.id,
                tool=step.tool,
                success=True,
                output=context.working_memory["review_content"],
            )

        return StepResult(step_id=step.id, tool=step.tool, success=True, output={"ok": True})


class TestAgentReActMode(unittest.IsolatedAsyncioTestCase):
    def test_agent_config_reads_mode(self) -> None:
        from backend.agent.config import AgentConfig

        os.environ["AGENT_MODE"] = "react"
        cfg = AgentConfig.from_env()
        self.assertEqual(cfg.agent_mode, "react")

        os.environ["AGENT_MODE"] = "PLAN"
        cfg2 = AgentConfig.from_env()
        self.assertEqual(cfg2.agent_mode, "plan")

    async def test_react_loop_runs_and_finalizes(self) -> None:
        from backend.agent.config import AgentConfig
        from backend.agent.context import ContextManager
        from backend.agent.core import AgentCore
        from backend.agent.mcp.registry import MCPToolRegistry
        from backend.agent.react.loop import ReActLoop
        from backend.agent.types import ActionResults, CompressedContext, UserProfile

        async def _noop(_args, _ctx):
            return {"ok": True}

        reg = MCPToolRegistry()
        for name in ("split_knowledge_points", "assemble_study_archive", "save_markdown_file", "review_content"):
            reg.register(name=name, description=name, execute=_noop)

        executor = _FakeExecutor(reg)
        ctx_mgr = ContextManager()
        agent = AgentCore(config=AgentConfig(planner_model="", reflector_model=""), executor=executor, context_manager=ctx_mgr)

        ctx: CompressedContext = ctx_mgr.create_context(
            user_profile=UserProfile(user_id="u", preferences={"subject": "高中数学"}),
            system_instructions="",
            current_task="测试主题",
        )
        ctx.working_memory["study_options"] = {"preset": "standard", "requirements": "", "strict_llm": False}
        results = ActionResults()

        calls = 0

        async def decide_next(_messages):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"thought": "先拆分知识点。", "action": "split_knowledge_points", "arguments": {"topic": "测试主题"}}
            return {"thought": "已有足够信息，进入收尾。", "action": "finish", "arguments": {}}

        loop = ReActLoop(config=agent.config, tool_registry=reg, decide_next=decide_next)

        events = []
        async for evt in loop.run(
            ctx=ctx,
            results=results,
            topic="测试主题",
            subject="高中数学",
            execute_concrete_step=lambda step: agent._execute_concrete_step(ctx=ctx, results=results, concrete_step=step),
            max_iterations=5,
            skip_export=True,
        ):
            events.append(evt)

        # Tool calls happened.
        tool_calls = [e for e in events if isinstance(e, dict) and e.get("event") == "tool_call"]
        self.assertTrue(tool_calls)

        # Final artifacts exist.
        self.assertTrue(isinstance(ctx.working_memory.get("split_knowledge_points"), dict))
        self.assertTrue(str(ctx.working_memory.get("markdown") or "").strip())
        self.assertEqual(str(ctx.working_memory.get("archive_path") or ""), "dummy.md")
        review = ctx.working_memory.get("review_content") or {}
        self.assertEqual(review.get("passed"), True)

