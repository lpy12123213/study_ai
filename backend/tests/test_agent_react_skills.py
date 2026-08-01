import json
import os
import unittest
from unittest import mock

from backend.agent.planning.skill_catalog import ALWAYS_ON_DIAGRAM_TOOLS, SKILLS


def _build_registry(*tool_names):
    from backend.agent.mcp.registry import MCPToolRegistry

    async def _noop(_args, _ctx):
        return {"ok": True}

    reg = MCPToolRegistry()
    for name in tool_names:
        reg.register(name=name, description=f"desc:{name}", execute=_noop)
    return reg


def _planning_and_diagram_tools():
    return set(SKILLS["planning"]["tools"]) | set(ALWAYS_ON_DIAGRAM_TOOLS)


def _decision_text(messages):
    return str(messages[-1].get("content") or "")


class TestAgentReActSkills(unittest.IsolatedAsyncioTestCase):
    def _make_ctx(self, *, skills_mode=True, active_skills=None, extra_wm=None):
        from backend.agent.config import AgentConfig
        from backend.agent.types import CompressedContext, UserProfile

        wm = {"study_options": {"preset": "standard", "requirements": ""}}
        if active_skills is not None:
            wm["active_skills"] = active_skills
        if extra_wm:
            wm.update(extra_wm)
        ctx = CompressedContext(
            user_profile=UserProfile(user_id="u", preferences={"subject": "高中数学"}),
            system_instructions="",
            current_task="函数",
            working_memory=wm,
        )
        cfg = AgentConfig(planner_model="", reflector_model="", skills_mode=skills_mode)
        return ctx, cfg

    async def _run(self, cfg, ctx, reg, decisions):
        from backend.agent.react.loop import ReActLoop
        from backend.agent.types import ActionResults

        captured = []
        calls = []

        async def decide_next(messages):
            captured.append(messages)
            return decisions.pop(0)

        async def execute_concrete_step(step):
            calls.append(step.tool)
            yield {"event": "tool_call", "data": {"name": step.tool, "step_id": step.id}}
            ctx.working_memory.setdefault("step_results", []).append(step.tool)
            yield {
                "event": "tool_result",
                "data": {"step_id": step.id, "name": step.tool, "success": True, "output": {"ok": True}},
            }

        results = ActionResults()
        loop = ReActLoop(config=cfg, tool_registry=reg, decide_next=decide_next)
        events = [
            evt
            async for evt in loop.run(
                ctx=ctx,
                results=results,
                topic="函数",
                subject="高中数学",
                execute_concrete_step=execute_concrete_step,
                max_iterations=10,
                skip_export=True,
            )
        ]
        return ctx, captured, calls, events

    async def test_initial_injected_tools_are_planning_only(self) -> None:
        reg = _build_registry(*(t for skill in SKILLS.values() for t in skill["tools"]))
        ctx, cfg = self._make_ctx()
        ctx, captured, calls, _events = await self._run(
            cfg,
            ctx,
            reg,
            [
                {"thought": "enough", "action": "finish", "arguments": {}},
            ],
        )

        prompt = _decision_text(captured[0])
        # planning tools present.
        self.assertIn("split_knowledge_points", prompt)
        # research / examples / writing / gated-diagram tools NOT injected.
        for name in ("web_search_knowledge", "search_examples", "generate_study_material", "tikz_to_svg"):
            self.assertNotIn(name, prompt)
        # always-on diagram tools still injected (legacy preservation).
        self.assertIn("generate_diagrams", prompt)

    async def test_load_skill_expands_tools_next_iteration(self) -> None:
        reg = _build_registry(*(t for skill in SKILLS.values() for t in skill["tools"]))
        ctx, cfg = self._make_ctx()
        ctx, captured, calls, _events = await self._run(
            cfg,
            ctx,
            reg,
            [
                {"thought": "load research", "action": "load_skill", "arguments": {"skill": "research"}},
                {"thought": "research now", "action": "web_search_knowledge", "arguments": {"knowledge_point": "KP"}},
                {"thought": "done", "action": "finish", "arguments": {}},
            ],
        )

        self.assertEqual(ctx.working_memory["active_skills"], ["planning", "research"])
        # research tools visible only after load_skill (second decision).
        self.assertNotIn("web_search_knowledge", _decision_text(captured[0]))
        self.assertIn("web_search_knowledge", _decision_text(captured[1]))
        # the now-loaded research tool actually executes.
        self.assertIn("web_search_knowledge", calls)
        # load_skill observation is recorded in the scratchpad of the next prompt.
        self.assertIn("已激活 skill `research`", _decision_text(captured[1]))
        # The FULL skill instruction body reaches the LLM via the decision
        # message (not the 180-char-clipped scratchpad observation). Assert on
        # distinctive content from agent.skills.research.v1, including its tail,
        # to prove it is not truncated.
        prompt2 = _decision_text(captured[1])
        self.assertIn("Loaded skill instructions", prompt2)
        self.assertIn("你是「research」技能的使用指引", prompt2)
        self.assertIn('batch_mode="per_knowledge_point" 批量检索', prompt2)
        # The bootstrap planning instruction is present from the first round.
        self.assertIn("你是「planning」技能的使用指引", _decision_text(captured[0]))

    async def test_load_skill_does_not_consume_llm_calls(self) -> None:
        from backend.agent.config import AgentConfig

        reg = _build_registry(*(t for skill in SKILLS.values() for t in skill["tools"]))
        ctx, cfg = self._make_ctx()
        # Tight budget: load_skill + 1 real tool + finish must all fit, proving
        # load_skill does not burn the LLM decision budget beyond one decision.
        cfg = AgentConfig(planner_model="", reflector_model="", skills_mode=True, react_llm_call_budget=4)

        decision_calls = []

        async def decide_next(messages):
            decision_calls.append(messages)
            decisions = [
                {"thought": "load", "action": "load_skill", "arguments": {"skill": "research"}},
                {"thought": "research", "action": "web_search_knowledge", "arguments": {"knowledge_point": "KP"}},
                {"thought": "done", "action": "finish", "arguments": {}},
            ]
            return decisions[len(decision_calls) - 1]

        from backend.agent.react.loop import ReActLoop
        from backend.agent.types import ActionResults

        calls = []

        async def execute_concrete_step(step):
            calls.append(step.tool)
            yield {"event": "tool_call", "data": {"name": step.tool, "step_id": step.id}}
            yield {"event": "tool_result", "data": {"step_id": step.id, "name": step.tool, "success": True, "output": {}}}

        results = ActionResults()
        loop = ReActLoop(config=cfg, tool_registry=reg, decide_next=decide_next)
        async for _evt in loop.run(
            ctx=ctx,
            results=results,
            topic="函数",
            subject="高中数学",
            execute_concrete_step=execute_concrete_step,
            max_iterations=10,
            skip_export=True,
        ):
            pass

        # Exactly 3 decisions (load_skill / web_search / finish) - no phantom
        # LLM round-trip for load_skill, and the real tool still runs under a
        # tight budget.
        self.assertEqual(len(decision_calls), 3)
        self.assertIn("web_search_knowledge", calls)
        self.assertNotIn("load_skill", calls)

    async def test_unloaded_tool_soft_guide_observation(self) -> None:
        reg = _build_registry(*(t for skill in SKILLS.values() for t in skill["tools"]))
        ctx, cfg = self._make_ctx()
        ctx, captured, calls, _events = await self._run(
            cfg,
            ctx,
            reg,
            [
                {"thought": "try research tool", "action": "web_search_knowledge", "arguments": {"knowledge_point": "KP"}},
                {"thought": "done", "action": "finish", "arguments": {}},
            ],
        )

        # The unloaded tool is soft-guided (FAILED) and never executes.
        self.assertNotIn("web_search_knowledge", calls)
        prompt = _decision_text(captured[1])
        self.assertIn("Quality: FAILED (skill_not_loaded)", prompt)
        self.assertIn('请先 load_skill("research")', prompt)

    async def test_invalid_skill_returns_failed_observation(self) -> None:
        reg = _build_registry(*(t for skill in SKILLS.values() for t in skill["tools"]))
        ctx, cfg = self._make_ctx(active_skills=["planning"])
        ctx, captured, calls, _events = await self._run(
            cfg,
            ctx,
            reg,
            [
                {"thought": "load bogus", "action": "load_skill", "arguments": {"skill": "does-not-exist"}},
                {"thought": "done", "action": "finish", "arguments": {}},
            ],
        )

        self.assertEqual(ctx.working_memory["active_skills"], ["planning"])
        prompt = _decision_text(captured[1])
        self.assertIn("Quality: FAILED (skill_not_available)", prompt)

    async def test_active_skills_round_trip_via_to_json(self) -> None:
        ctx, cfg = self._make_ctx(active_skills=["planning", "research"])
        payload = json.loads(ctx.to_json())
        self.assertEqual(payload["working_memory"]["active_skills"], ["planning", "research"])

    async def test_resume_merge_restores_active_skills(self) -> None:
        from backend.agent.config import AgentConfig
        from backend.agent.context import ContextManager
        from backend.agent.run_init import initialize_run
        from backend.agent.types import UserProfile

        class _FakeMemoryStore:
            async def get_user_profile(self, *, user_id):
                return UserProfile(user_id=user_id, preferences={"subject": "高中数学"})

        class _FakeSemanticStore:
            async def search(self, **kwargs):
                return []

        out = {}
        async for _evt in initialize_run(
            user_input="函数",
            user_id="u",
            preferences={},
            options={},
            resume_working_memory={
                "active_skills": ["planning", "research"],
                "study_options": {"preset": "deep"},
            },
            iteration_offset=0,
            max_iterations=3,
            out=out,
            config=AgentConfig(skills_mode=True),
            memory_store=_FakeMemoryStore(),
            semantic_store=_FakeSemanticStore(),
            context_manager=ContextManager(),
            system_instructions="",
            set_state=lambda _s: None,
        ):
            pass

        ctx = out["ctx"]
        # Resume merge restored active_skills and the setdefault bootstrap did
        # not clobber it.
        self.assertEqual(ctx.working_memory["active_skills"], ["planning", "research"])

    async def test_fresh_run_defaults_active_skills_to_planning(self) -> None:
        from backend.agent.config import AgentConfig
        from backend.agent.context import ContextManager
        from backend.agent.run_init import initialize_run
        from backend.agent.types import UserProfile

        class _FakeMemoryStore:
            async def get_user_profile(self, *, user_id):
                return UserProfile(user_id=user_id, preferences={"subject": "高中数学"})

        class _FakeSemanticStore:
            async def search(self, **kwargs):
                return []

        out = {}
        async for _evt in initialize_run(
            user_input="函数",
            user_id="u",
            preferences={},
            options={},
            resume_working_memory=None,
            iteration_offset=0,
            max_iterations=3,
            out=out,
            config=AgentConfig(skills_mode=True),
            memory_store=_FakeMemoryStore(),
            semantic_store=_FakeSemanticStore(),
            context_manager=ContextManager(),
            system_instructions="",
            set_state=lambda _s: None,
        ):
            pass

        self.assertEqual(out["ctx"].working_memory["active_skills"], ["planning"])

    async def test_default_skills_mode_off_preserves_full_list_behavior(self) -> None:
        reg = _build_registry(*(t for skill in SKILLS.values() for t in skill["tools"]))
        ctx, cfg = self._make_ctx(skills_mode=False, active_skills=["planning"])
        ctx, captured, calls, _events = await self._run(
            cfg,
            ctx,
            reg,
            [
                # web_search_knowledge is NOT in active planning skill, but with
                # skills_mode off the full registry list is injected.
                {"thought": "research", "action": "web_search_knowledge", "arguments": {"knowledge_point": "KP"}},
                {"thought": "done", "action": "finish", "arguments": {}},
            ],
        )

        self.assertIn("web_search_knowledge", _decision_text(captured[0]))
        self.assertIn("web_search_knowledge", calls)
        # active_skills untouched.
        self.assertEqual(ctx.working_memory.get("active_skills"), ["planning"])

    async def test_skills_mode_off_hides_load_skill_docs(self) -> None:
        reg = _build_registry(*(t for skill in SKILLS.values() for t in skill["tools"]))
        ctx, cfg = self._make_ctx(skills_mode=False)
        ctx, captured, calls, _events = await self._run(
            cfg,
            ctx,
            reg,
            [
                {"thought": "done", "action": "finish", "arguments": {}},
            ],
        )

        full_text = "\n".join(str(m.get("content") or "") for m in captured[0])
        # No load_skill documentation anywhere: the stable manifest, the
        # special-action docs, and the loaded-instructions block are all
        # skills-mode-only.
        self.assertNotIn("load_skill", full_text)
        self.assertNotIn("Available skills", full_text)
        self.assertNotIn("Loaded skill instructions", full_text)

    async def test_skills_mode_off_load_skill_falls_through_to_tool_not_found(self) -> None:
        reg = _build_registry(*(t for skill in SKILLS.values() for t in skill["tools"]))
        ctx, cfg = self._make_ctx(skills_mode=False)  # no active_skills key in wm
        ctx, captured, calls, _events = await self._run(
            cfg,
            ctx,
            reg,
            [
                {"thought": "load", "action": "load_skill", "arguments": {"skill": "research"}},
                {"thought": "done", "action": "finish", "arguments": {}},
            ],
        )

        # Same legacy path as any unknown action: tool_not_found, no fake success.
        self.assertNotIn("load_skill", calls)
        prompt = _decision_text(captured[1])
        self.assertIn("Quality: FAILED (tool_not_found)", prompt)
        self.assertIn("tool_not_found: load_skill", prompt)
        # No active_skills write of any kind.
        self.assertNotIn("active_skills", ctx.working_memory)

    async def test_skills_mode_off_run_init_leaves_no_active_skills_key(self) -> None:
        from backend.agent.config import AgentConfig
        from backend.agent.context import ContextManager
        from backend.agent.run_init import initialize_run
        from backend.agent.types import UserProfile

        class _FakeMemoryStore:
            async def get_user_profile(self, *, user_id):
                return UserProfile(user_id=user_id, preferences={"subject": "高中数学"})

        class _FakeSemanticStore:
            async def search(self, **kwargs):
                return []

        out = {}
        async for _evt in initialize_run(
            user_input="函数",
            user_id="u",
            preferences={},
            options={},
            resume_working_memory=None,
            iteration_offset=0,
            max_iterations=3,
            out=out,
            config=AgentConfig(),  # skills_mode defaults to False
            memory_store=_FakeMemoryStore(),
            semantic_store=_FakeSemanticStore(),
            context_manager=ContextManager(),
            system_instructions="",
            set_state=lambda _s: None,
        ):
            pass

        self.assertNotIn("active_skills", out["ctx"].working_memory)

    def test_stable_messages_do_not_depend_on_active_skills(self) -> None:
        from backend.agent.react.prompts import build_react_messages

        ctx_base, _cfg = self._make_ctx(active_skills=["planning"])
        ctx_more, _cfg2 = self._make_ctx(active_skills=["planning", "research", "examples"])
        kwargs = {
            "topic": "函数",
            "subject": "高中数学",
            "tools": [{"name": "split_knowledge_points", "description": "拆分"}],
            "scratchpad": "",
            "iteration": 0,
            "max_iterations": 3,
            "budget_remaining": 5,
            "skills_mode": True,
        }
        m1 = build_react_messages(ctx=ctx_base, **kwargs)
        m2 = build_react_messages(ctx=ctx_more, **kwargs)

        # The two cacheable (stable) messages are byte-identical before/after a
        # load_skill: the manifest lists ALL domain skills statically.
        self.assertEqual(m1[0], m2[0])
        self.assertEqual(m1[1], m2[1])

        stable = str(m1[1]["content"])
        for name in ("planning", "research", "examples", "writing", "export", "diagrams"):
            self.assertIn(f"- {name}:", stable)

        # The loaded/unloaded state lives in the per-iteration decision message.
        self.assertNotIn("你是「research」技能的使用指引", str(m1[2]["content"]))
        self.assertIn("你是「research」技能的使用指引", str(m2[2]["content"]))
        self.assertIn("你是「examples」技能的使用指引", str(m2[2]["content"]))

    def _injected_tool_names(self, cfg, ctx, reg):
        from backend.agent.react.loop import ReActLoop

        loop = ReActLoop(config=cfg, tool_registry=reg)
        return {str(t.get("name") or "").strip() for t in loop._injectable_tools(ctx)}

    def test_env_enable_questions_unlocks_question_tool(self) -> None:
        reg = _build_registry(*(t for skill in SKILLS.values() for t in skill["tools"]))
        ctx, cfg = self._make_ctx(active_skills=["planning", "examples"])
        # Canonical env fallback: no per-task option, env var decides.
        with mock.patch.dict(os.environ, {"STUDY_MATERIALS_ENABLE_QUESTIONS": "1"}):
            names = self._injected_tool_names(cfg, ctx, reg)
        self.assertIn("search_questions_by_knowledge", names)

    def test_questions_flag_defaults_off_without_env_or_option(self) -> None:
        reg = _build_registry(*(t for skill in SKILLS.values() for t in skill["tools"]))
        ctx, cfg = self._make_ctx(active_skills=["planning", "examples"])
        with mock.patch.dict(os.environ, {"STUDY_MATERIALS_ENABLE_QUESTIONS": "0"}):
            names = self._injected_tool_names(cfg, ctx, reg)
        self.assertNotIn("search_questions_by_knowledge", names)

    def test_extra_tools_canonical_default_and_env_fallback(self) -> None:
        reg = _build_registry(*(t for skill in SKILLS.values() for t in skill["tools"]))
        ctx, cfg = self._make_ctx(active_skills=["planning", "research"])

        # Canonical default (no option, env off) keeps research extras OUT.
        with mock.patch.dict(os.environ, {"STUDY_MATERIALS_ENABLE_EXTRA_TOOLS": "0"}):
            names_off = self._injected_tool_names(cfg, ctx, reg)
        self.assertNotIn("wikipedia_search", names_off)
        self.assertIn("web_search_knowledge", names_off)  # core research tool stays

        # Env fallback surfaces them.
        with mock.patch.dict(os.environ, {"STUDY_MATERIALS_ENABLE_EXTRA_TOOLS": "1"}):
            names_on = self._injected_tool_names(cfg, ctx, reg)
        self.assertIn("wikipedia_search", names_on)


if __name__ == "__main__":
    unittest.main()
