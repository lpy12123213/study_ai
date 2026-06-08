from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.agent import auto_research as agent_auto_research
from backend.agent import run_init as agent_run_init
from backend.agent import streaming as agent_streaming
from backend.agent.config import AgentConfig
from backend.agent.context import ContextManager
from backend.agent.executor import Executor
from backend.agent.memory import MemoryStore, SemanticStore
from backend.agent.planning.planner import Planner
from backend.agent.policy import StudyMaterialsPolicy
from backend.agent.react.loop import ReActLoop
from backend.agent.reflector import Reflector
from backend.agent.streaming import _extract_kp_source_text, _strip_markdown_headings
from backend.agent.tool_dispatch import ToolDispatcher
from backend.agent.types import (
    ActionResults,
    AgentState,
    CompressedContext,
    ExecutionPlan,
    PlanStep,
    ReflectionResult,
    UserProfile,
    agent_event,
)
from backend.core.logging_utils import get_logger
from backend.core.text_utils import clip_text as _clip_chars
from backend.llm.client import cacheable_message, chat_completion_text, is_llm_configured
from backend.llm.prompts import create_default_prompt_registry

logger = get_logger(__name__)


def _agent_system_instructions() -> str:
    return create_default_prompt_registry().render("agent.core.system_instructions.v1").content


def _subagent_summary_system_prompt() -> str:
    return create_default_prompt_registry().render("agent.subagent.summary_plain.v1").content


SYSTEM_INSTRUCTIONS = _agent_system_instructions()


class AgentCore:
    """Plan-Act-Reflect agent core with streaming events."""

    def __init__(
        self,
        *,
        config: Optional[AgentConfig] = None,
        memory_store: Optional[MemoryStore] = None,
        semantic_store: Optional[SemanticStore] = None,
        context_manager: Optional[ContextManager] = None,
        planner: Optional[Planner] = None,
        executor: Optional[Executor] = None,
        reflector: Optional[Reflector] = None,
    ) -> None:
        self.config = config or AgentConfig.from_env()
        self.memory_store = memory_store or MemoryStore()
        self.semantic_store = semantic_store or SemanticStore()
        self.context_manager = context_manager or ContextManager(config=self.config)
        self.planner = planner or Planner(config=self.config)
        self.executor = executor or Executor(config=self.config)
        self.reflector = reflector or Reflector(config=self.config)

        self.state: AgentState = AgentState.IDLE
        self.last_context: Optional[CompressedContext] = None
        self._post_done_tasks: set[asyncio.Task[None]] = set()

        self._tool_dispatch = ToolDispatcher(
            config=self.config,
            executor=self.executor,
            context_manager=self.context_manager,
            set_state=self._set_state,
            summarize_subagent=lambda ctx, kp: self._summarize_subagent(ctx=ctx, kp=kp),
            store_subagent_summary=lambda ctx, kp, summary: self._store_subagent_summary(
                ctx=ctx, kp=kp, summary=summary
            ),
            start_export_subagent=lambda ctx, kp: self._start_export_subagent(ctx=ctx, kp=kp),
            end_export_subagent=lambda ctx, kp, content: self._end_export_subagent(ctx=ctx, kp=kp, content=content),
        )

    def _set_state(self, state: AgentState) -> None:
        self.state = state

    def _schedule_post_done_job(self, name: str, coro: Any) -> Optional[asyncio.Task[None]]:
        task = asyncio.create_task(coro, name=name)
        self._post_done_tasks.add(task)

        def _finalize(done_task: asyncio.Task[None]) -> None:
            self._post_done_tasks.discard(done_task)
            try:
                done_task.result()
            except asyncio.CancelledError:
                logger.debug("%s_canceled", name)
            except Exception:
                logger.warning("%s_failed", name, exc_info=True)

        task.add_done_callback(_finalize)
        return task

    def _schedule_semantic_upsert(
        self,
        *,
        user_id: str,
        docs: List[Any],
        timeout_s: float,
    ) -> Optional[asyncio.Task[None]]:
        if not docs:
            return None

        async def _run() -> None:
            await asyncio.sleep(0)
            await asyncio.wait_for(
                self.semantic_store.upsert(user_id=user_id, docs=docs),
                timeout=timeout_s,
            )

        return self._schedule_post_done_job("semantic_store_upsert", _run())

    async def _summarize_subagent(self, *, ctx: CompressedContext, kp: str) -> str:
        kp = str(kp or "").strip()
        if not kp:
            return ""

        src = _extract_kp_source_text(ctx, kp=kp)
        if not src:
            return ""

        model = self.config.model_for_tier(
            "fast",
            fallback=str(self.config.summarizer_model or self.config.planner_model or ""),
        )
        if model and is_llm_configured():
            prompt = (
                "Write a concise summary for the knowledge point below.\n"
                "- Length: 100-200 Chinese characters or the equivalent length in the source language.\n"
                "- Output only the summary body. Do not use Markdown, bullets, numbering, or headings.\n"
                "- Focus on the core definition, key conclusions, common misconceptions, or solution framework when applicable.\n"
                "- Match the language of the knowledge point/source material unless the task context clearly requires another language.\n\n"
                f"Knowledge point: {kp}\n"
                f"Material excerpt:\n{src}\n"
            )
            try:
                text = await chat_completion_text(
                    messages=[
                        cacheable_message("system", _subagent_summary_system_prompt()),
                        {"role": "user", "content": prompt},
                    ],
                    model=model,
                    temperature=0.2,
                    max_tokens=280,
                    retries=2,
                    req_id_prefix="subagent-sum",
                )
                text = str(text or "").strip()
                if text:
                    text = _strip_markdown_headings(text).replace("```", "").strip()
                    return _clip_chars(text, max_chars=220)
            except Exception:
                logger.warning("agent_subagent_summary_llm_failed", exc_info=True)

        return _clip_chars(_strip_markdown_headings(src), max_chars=220)

    def _store_subagent_summary(self, *, ctx: CompressedContext, kp: str, summary: str) -> None:
        kp = str(kp or "").strip()
        summary = str(summary or "").strip()
        if not kp or not summary:
            return

        bucket = ctx.working_memory.get("subagent_summaries")
        if not isinstance(bucket, dict):
            bucket = {}
            ctx.working_memory["subagent_summaries"] = bucket
        bucket[kp] = summary

    def _set_plan_summary(
        self,
        *,
        ctx: CompressedContext,
        topic: str,
        profile: UserProfile,
        plan: Optional[ExecutionPlan],
        export_only: bool,
    ) -> None:
        opts = ctx.working_memory.get("study_options")
        opts = dict(opts) if isinstance(opts, dict) else {}

        preset = str(opts.get("preset") or "").strip().lower()
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = "standard"

        requirements = _clip_chars(str(opts.get("requirements") or "").strip(), max_chars=900)
        subject = str(profile.preferences.get("subject") or "").strip()
        kps = self._get_split_knowledge_points(ctx)

        rationale = _clip_chars(str(getattr(plan, "rationale", "") or "").strip(), max_chars=900)
        ctx.working_memory["plan_summary"] = {
            "topic": str(topic or "").strip(),
            "subject": subject,
            "preset": preset,
            "requirements": requirements,
            "knowledge_points": kps,
            "export_only": bool(export_only),
            "rationale": rationale,
        }

    def _get_split_knowledge_points(self, ctx: CompressedContext) -> List[str]:
        return self._tool_dispatch._get_split_knowledge_points(ctx)

    async def _execute_step_block(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        steps: List[PlanStep],
    ) -> AsyncIterator[Dict[str, Any]]:
        async for evt in self._tool_dispatch.execute_step_block(ctx=ctx, results=results, steps=steps):
            yield evt

    async def _execute_concrete_step(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        concrete_step: PlanStep,
    ) -> AsyncIterator[Dict[str, Any]]:
        async for evt in self._tool_dispatch.execute_concrete_step(
            ctx=ctx,
            results=results,
            concrete_step=concrete_step,
        ):
            yield evt

    async def _ensure_planner_knowledge_points(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        user_input: str,
        profile: UserProfile,
    ) -> AsyncIterator[Dict[str, Any]]:
        async for evt in self._tool_dispatch.ensure_planner_knowledge_points(
            ctx=ctx,
            results=results,
            user_input=user_input,
            profile=profile,
        ):
            yield evt

    async def _execute_foreach_block(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        block: List[PlanStep],
        fallback_kp: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        async for evt in self._tool_dispatch.execute_foreach_block(
            ctx=ctx, results=results, block=block, fallback_kp=fallback_kp
        ):
            yield evt

    async def _execute_plan_steps(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        plan: ExecutionPlan,
        user_input: str,
        skip_export: bool,
    ) -> AsyncIterator[Dict[str, Any]]:
        async for evt in self._tool_dispatch.execute_plan_steps(
            ctx=ctx, results=results, plan=plan, user_input=user_input, skip_export=skip_export
        ):
            yield evt

    async def _initialize_run(
        self,
        *,
        user_input: str,
        user_id: str,
        preferences: Optional[Dict[str, Any]],
        options: Optional[Dict[str, Any]],
        resume_working_memory: Optional[Dict[str, Any]],
        iteration_offset: int,
        max_iterations: Optional[int],
        out: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        async for evt in agent_run_init.initialize_run(
            user_input=user_input,
            user_id=user_id,
            preferences=preferences,
            options=options,
            resume_working_memory=resume_working_memory,
            iteration_offset=iteration_offset,
            max_iterations=max_iterations,
            out=out,
            config=self.config,
            memory_store=self.memory_store,
            semantic_store=self.semantic_store,
            context_manager=self.context_manager,
            system_instructions=SYSTEM_INSTRUCTIONS,
            set_state=self._set_state,
        ):
            yield evt

        ctx = out.get("ctx")
        if isinstance(ctx, CompressedContext):
            self.last_context = ctx

    def _build_export_only_plan(self, *, user_input: str, subject: str, compile_err: str) -> ExecutionPlan:
        return ExecutionPlan(
            topic=user_input,
            rationale="continue_mode=fix_export: rerun export-only steps",
            steps=[
                PlanStep(
                    id=f"export_study_markdown-continue-{uuid.uuid4().hex[:8]}",
                    title="Export Markdown (download link)",
                    tool="export_study_markdown",
                    arguments={},
                    thought="Publish the current Markdown as a downloadable file.",
                ),
                PlanStep(
                    id=f"convert_markdown_to_latex-continue-{uuid.uuid4().hex[:8]}",
                    title="Convert Markdown to LaTeX (ElegantBook)",
                    tool="convert_markdown_to_latex",
                    arguments={"topic": user_input, "subject": subject},
                    thought="Convert the current Markdown to LaTeX and publish the .tex download link.",
                ),
                PlanStep(
                    id=f"refine_latex-continue-{uuid.uuid4().hex[:8]}",
                    title="Refine LaTeX (optional)",
                    tool="refine_latex",
                    arguments={"topic": user_input, "subject": subject, "compile_error": compile_err},
                    thought="Optionally refine LaTeX to improve compilation success rate.",
                ),
                PlanStep(
                    id=f"compile_latex_to_pdf-continue-{uuid.uuid4().hex[:8]}",
                    title="Compile LaTeX to PDF",
                    tool="compile_latex_to_pdf",
                    arguments={"topic": user_input},
                    thought="Compile LaTeX into a PDF and publish the download link.",
                ),
            ],
        )

    async def _start_export_subagent(self, *, ctx: CompressedContext, kp: str) -> AsyncIterator[Dict[str, Any]]:
        ctx.working_memory["_export_subagent_kp"] = kp
        yield agent_event("subagent_start", {"knowledge_point": kp, "content": "SubAgent 启动：导出与编译（LaTeX/PDF）。"})
        yield agent_event("status", {"content": "SubAgent 启动：导出与编译（LaTeX/PDF）。"})

    async def _end_export_subagent(
        self,
        *,
        ctx: CompressedContext,
        kp: str,
        content: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        ctx.working_memory.pop("_export_subagent_kp", None)
        yield agent_event("subagent_end", {"knowledge_point": kp, "content": content})
        yield agent_event("status", {"content": content})

    # Run loop methods are added below.

    async def _run_iterations(
        self,
        *,
        ctx: CompressedContext,
        profile: UserProfile,
        policy: StudyMaterialsPolicy,
        user_input: str,
        iter_offset: int,
        budget: int,
        export_only: bool,
        skip_export: bool,
        out: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        iteration = iter_offset
        plan: Optional[ExecutionPlan] = None
        results = ActionResults()
        reflection: Optional[ReflectionResult] = None

        for iteration in range(iter_offset, iter_offset + max(1, int(budget or 1))):
            results = ActionResults()
            self.state = AgentState.PLANNING
            yield agent_event("status", {"content": f"Plan 阶段：规划（第 {iteration + 1} 轮）…"})

            degraded_reason = ""
            if iteration == 0 and (not export_only):
                async for evt in self._ensure_planner_knowledge_points(
                    ctx=ctx,
                    results=results,
                    user_input=user_input,
                    profile=profile,
                ):
                    yield evt

            if export_only:
                subject = str(profile.preferences.get("subject") or "").strip()
                compile_err = str(ctx.working_memory.get("_latex_last_compile_error") or "").strip()
                yield agent_event("status", {"content": "Continue mode: fix_export (rerun export-only steps)."})
                plan = self._build_export_only_plan(user_input=user_input, subject=subject, compile_err=compile_err)
            else:
                plan, degraded_reason = await self.planner.plan(
                    topic=user_input,
                    user_profile=profile,
                    context=ctx,
                    iteration=iteration,
                    tool_registry=self.executor.tool_registry,
                )
                if degraded_reason in {"timeout", "error"}:
                    yield agent_event("degraded_plan", {"reason": degraded_reason})

            self._set_plan_summary(ctx=ctx, topic=user_input, profile=profile, plan=plan, export_only=export_only)

            if plan.rationale:
                yield agent_event("status", {"content": plan.rationale})

            self.state = AgentState.ACTING
            yield agent_event("status", {"content": "Act 阶段：执行工具链…"})

            async for evt in self._execute_plan_steps(
                ctx=ctx,
                results=results,
                plan=plan,
                user_input=user_input,
                skip_export=skip_export,
            ):
                yield evt

            async for evt in agent_auto_research.maybe_auto_research(
                ctx=ctx,
                results=results,
                plan=plan,
                policy=policy,
                user_input=user_input,
                execute_concrete_step=self._execute_concrete_step,
            ):
                yield evt

            async for evt in agent_auto_research.maybe_auto_revise(
                ctx=ctx,
                results=results,
                plan=plan,
                policy=policy,
                execute_concrete_step=self._execute_concrete_step,
            ):
                yield evt

            if bool(ctx.working_memory.get("_abort_execution")):
                fatal = ctx.working_memory.get("_fatal_error")
                fatal_msg = ""
                if isinstance(fatal, dict):
                    fatal_msg = str(fatal.get("error") or "").strip()
                    tool_name = str(fatal.get("tool") or "").strip()
                    if tool_name:
                        fatal_msg = f"{tool_name}: {fatal_msg}" if fatal_msg else tool_name
                reflection = ReflectionResult(
                    passed=True,
                    issues=[fatal_msg] if fatal_msg else ["关键步骤失败，已停止后续执行。"],
                    summary="执行中断：已停止后续步骤并返回当前可用结果。",
                )
                break

            self.state = AgentState.REFLECTING
            yield agent_event("status", {"content": "Reflect 阶段：自检与审查…"})
            reflection = await self.reflector.reflect(topic=user_input, plan=plan, results=results, context=ctx)

            if reflection.summary:
                yield agent_event("status", {"content": reflection.summary})

            if reflection.passed:
                break

            self.state = AgentState.ITERATING
            yield agent_event(
                "status",
                {
                    "content": "发现问题，准备迭代修正…\n"
                    + ("\n".join(f"- {x}" for x in (reflection.issues or [])[:6]) if reflection.issues else ""),
                },
            )
            await self.context_manager.on_reflection(ctx, reflection)

        out["iteration"] = iteration
        out["plan"] = plan
        out["results"] = results
        out["reflection"] = reflection

    async def _run_react(
        self,
        *,
        ctx: CompressedContext,
        profile: UserProfile,
        user_input: str,
        max_tool_iterations: int,
        skip_export: bool,
        out: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        """ReAct loop: LLM decides the next tool to call dynamically."""

        subject = str(profile.preferences.get("subject") or "").strip()
        plan = ExecutionPlan(topic=user_input, steps=[], rationale="ReAct")
        results = ActionResults()
        reflection: Optional[ReflectionResult] = None

        # Note: the LLM agent decides when/how to split knowledge points via the
        # split_knowledge_points tool. We no longer force this as a deterministic
        # first step so the agent can choose alternative strategies (e.g. for very
        # focused topics it may skip the split entirely).

        loop = ReActLoop(config=self.config, tool_registry=self.executor.tool_registry)
        async for evt in loop.run(
            ctx=ctx,
            results=results,
            topic=user_input,
            subject=subject,
            execute_concrete_step=lambda step: self._execute_concrete_step(
                ctx=ctx,
                results=results,
                concrete_step=step,
            ),
            execute_step_block=lambda steps: self._execute_step_block(
                ctx=ctx,
                results=results,
                steps=steps,
            ),
            max_iterations=max_tool_iterations,
            skip_export=skip_export,
        ):
            yield evt

        if bool(ctx.working_memory.get("_abort_execution")):
            fatal = ctx.working_memory.get("_fatal_error")
            fatal_msg = ""
            if isinstance(fatal, dict):
                fatal_msg = str(fatal.get("error") or "").strip()
                tool_name = str(fatal.get("tool") or "").strip()
                if tool_name:
                    fatal_msg = f"{tool_name}: {fatal_msg}" if fatal_msg else tool_name
            reflection = ReflectionResult(
                passed=True,
                issues=[fatal_msg] if fatal_msg else ["关键步骤失败，已停止后续执行。"],
                summary="执行中断：已停止后续步骤并返回当前可用结果。",
            )
        else:
            review = ctx.working_memory.get("review_content")
            if isinstance(review, dict) and review.get("passed") is True:
                reflection = ReflectionResult(
                    passed=True,
                    issues=[],
                    suggestions=[],
                    summary="review_content 已通过：跳过后置 reflector.reflect()（节省一次 LLM 调用）。",
                )
                yield agent_event("status", {"content": reflection.summary})
            else:
                self.state = AgentState.REFLECTING
                yield agent_event("status", {"content": "Reflect 阶段：自检与审查…"})
                reflection = await self.reflector.reflect(topic=user_input, plan=plan, results=results, context=ctx)
                if reflection.summary:
                    yield agent_event("status", {"content": reflection.summary})

        out["iteration"] = 0
        out["plan"] = plan
        out["results"] = results
        out["reflection"] = reflection

    async def run(
        self,
        user_input: str,
        *,
        user_id: str = "anonymous",
        preferences: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
        resume_working_memory: Optional[Dict[str, Any]] = None,
        iteration_offset: int = 0,
        max_iterations: Optional[int] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Main entry. Streams AgentEvents compatible with the frontend SSE handler."""

        user_input = (user_input or "").strip()
        if not user_input:
            yield agent_event("error", {"message": "Empty input"})
            return

        iteration = 0
        plan: Optional[ExecutionPlan] = None
        results = ActionResults()
        reflection: Optional[ReflectionResult] = None

        try:
            init: Dict[str, Any] = {}
            async for evt in self._initialize_run(
                user_input=user_input,
                user_id=user_id,
                preferences=preferences,
                options=options,
                resume_working_memory=resume_working_memory,
                iteration_offset=iteration_offset,
                max_iterations=max_iterations,
                out=init,
            ):
                yield evt

            profile: UserProfile = init["profile"]
            ctx: CompressedContext = init["ctx"]
            policy: StudyMaterialsPolicy = init["policy"]
            iter_offset = int(init.get("iter_offset") or 0)
            budget = int(init.get("budget") or 1)
            export_only = bool(init.get("export_only"))
            skip_export = bool(init.get("skip_export"))

            agent_mode = str(getattr(self.config, "agent_mode", "") or "plan").strip().lower()
            use_react = agent_mode == "react" and (not export_only)
            if use_react:
                # ReAct mode requires an LLM to decide the next tool; otherwise fall back to plan mode.
                normalized_model = str(self.config.planner_model or "").strip()
                if not (normalized_model and is_llm_configured()):
                    use_react = False

            if use_react:
                try:
                    tool_budget = (
                        int(max_iterations) if max_iterations is not None else int(self.config.react_max_iterations)
                    )
                except (TypeError, ValueError):
                    tool_budget = int(self.config.react_max_iterations or 20)

                # Scale tool budget by preset so research mode actually researches.
                preset_budget_floor = {
                    "quick": 6,
                    "standard": 14,
                    "deep": 24,
                    "research": 32,
                }
                opts_for_preset = ctx.working_memory.get("study_options")
                preset_key = ""
                if isinstance(opts_for_preset, dict):
                    preset_key = str(opts_for_preset.get("preset") or "").strip().lower()
                if preset_key not in preset_budget_floor:
                    preset_key = "standard"
                tool_budget = max(tool_budget, preset_budget_floor[preset_key])
                tool_budget = max(1, min(tool_budget, 60))

                react_state: Dict[str, Any] = {}
                async for evt in self._run_react(
                    ctx=ctx,
                    profile=profile,
                    user_input=user_input,
                    max_tool_iterations=tool_budget,
                    skip_export=skip_export,
                    out=react_state,
                ):
                    yield evt

                iteration = int(react_state.get("iteration") or 0)
                plan = react_state.get("plan") if isinstance(react_state.get("plan"), ExecutionPlan) else plan
                results = (
                    react_state.get("results")
                    if isinstance(react_state.get("results"), ActionResults)
                    else results
                )
                reflection = (
                    react_state.get("reflection")
                    if isinstance(react_state.get("reflection"), ReflectionResult)
                    else reflection
                )
            else:
                iter_state: Dict[str, Any] = {}
                async for evt in self._run_iterations(
                    ctx=ctx,
                    profile=profile,
                    policy=policy,
                    user_input=user_input,
                    iter_offset=iter_offset,
                    budget=budget,
                    export_only=export_only,
                    skip_export=skip_export,
                    out=iter_state,
                ):
                    yield evt

                iteration = int(iter_state.get("iteration") or iter_offset)
                plan = iter_state.get("plan") if isinstance(iter_state.get("plan"), ExecutionPlan) else plan
                results = iter_state.get("results") if isinstance(iter_state.get("results"), ActionResults) else results
                reflection = (
                    iter_state.get("reflection")
                    if isinstance(iter_state.get("reflection"), ReflectionResult)
                    else reflection
                )

            resolved = agent_streaming.resolve_markdown_and_archive_path(
                ctx=ctx,
                user_input=user_input,
                results=results,
            )
            archive_path = resolved["archive_path"]
            markdown = resolved["markdown"]

            try:
                semantic_timeout_s = float(os.getenv("AGENT_SEMANTIC_UPSERT_TIMEOUT_S") or "3.0")
                semantic_timeout_s = max(0.2, min(semantic_timeout_s, 30.0))
                docs = agent_streaming.build_semantic_docs_for_run(ctx=ctx, user_input=user_input, markdown=markdown)
                self._schedule_semantic_upsert(user_id=user_id, docs=docs, timeout_s=semantic_timeout_s)
            except Exception:
                logger.warning("semantic_store_upsert_schedule_failed", exc_info=True)

            async for evt in agent_streaming.compress_context(
                ctx=ctx,
                context_manager=self.context_manager,
                set_state=self._set_state,
            ):
                yield evt

            async for evt in agent_streaming.record_session(
                user_id=user_id,
                user_input=user_input,
                reflection=reflection,
                memory_store=self.memory_store,
            ):
                yield evt

            self.state = AgentState.COMPLETED
            md_url = str(ctx.working_memory.get("md_url") or "").strip()
            pdf_url = str(ctx.working_memory.get("pdf_url") or "").strip()
            tex_url = str(ctx.working_memory.get("tex_url") or "").strip()
            md_filename = str(ctx.working_memory.get("md_filename") or "").strip()
            pdf_filename = str(ctx.working_memory.get("pdf_filename") or "").strip()
            tex_filename = str(ctx.working_memory.get("tex_filename") or "").strip()
            fatal_error = ctx.working_memory.get("_fatal_error")
            fatal_error = dict(fatal_error) if isinstance(fatal_error, dict) else None
            per_kp_report = agent_streaming.build_per_kp_report(ctx=ctx)
            timing_report = agent_streaming.build_timing_report(ctx=ctx, per_kp_report=per_kp_report)
            yield agent_event(
                "done",
                {
                    "material": {
                        "topic": user_input,
                        "archive_path": archive_path,
                        "md_url": md_url,
                        "md_filename": md_filename,
                        "tex_url": tex_url,
                        "tex_filename": tex_filename,
                        "pdf_url": pdf_url,
                        "pdf_filename": pdf_filename,
                        "iteration": iteration + 1,
                        "passed": bool(reflection.passed) if reflection else True,
                        "issues": reflection.issues if reflection else [],
                        "error": fatal_error,
                    },
                    "per_kp_report": per_kp_report,
                    "timing_report": timing_report,
                },
            )

        except Exception as exc:  # pragma: no cover (best-effort safety)
            logger.exception("study_material_agent_run_failed")
            self.state = AgentState.ERROR
            yield agent_event("error", {"message": str(exc)})
