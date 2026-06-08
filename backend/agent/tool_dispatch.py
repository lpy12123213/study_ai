from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from backend.agent.config import AgentConfig
from backend.agent.execution_strategy import ExecutionStrategy, PerKnowledgePointStrategy
from backend.agent.streaming import (
    StopStepExecution,
    _clip_for_sse,
    maybe_capture_markdown_artifact,
    maybe_handle_step_failure,
)
from backend.agent.types import (
    ActionResults,
    AgentState,
    CompressedContext,
    ExecutionPlan,
    PlanStep,
    StepResult,
    UserProfile,
    agent_event,
)
from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


class ToolDispatcher:
    def __init__(
        self,
        *,
        config: AgentConfig,
        executor: Any,
        context_manager: Any,
        set_state: Callable[[AgentState], None],
        summarize_subagent: Callable[[CompressedContext, str], Awaitable[str]],
        store_subagent_summary: Callable[[CompressedContext, str, str], None],
        start_export_subagent: Callable[[CompressedContext, str], AsyncIterator[Dict[str, Any]]],
        end_export_subagent: Callable[[CompressedContext, str, str], AsyncIterator[Dict[str, Any]]],
        execution_strategy: Optional[ExecutionStrategy] = None,
    ) -> None:
        self.config = config
        self.executor = executor
        self.context_manager = context_manager
        self._set_state = set_state
        self._summarize_subagent = summarize_subagent
        self._store_subagent_summary = store_subagent_summary
        self._start_export_subagent = start_export_subagent
        self._end_export_subagent = end_export_subagent
        self.execution_strategy = execution_strategy or PerKnowledgePointStrategy()

    def _get_split_knowledge_points(self, ctx: CompressedContext) -> List[str]:
        split_res = ctx.working_memory.get("split_knowledge_points") or {}
        kps_raw = split_res.get("knowledge_points") if isinstance(split_res, dict) else []
        kps = (
            [
                str(x or "").strip()
                for x in (kps_raw or [])
                if isinstance(x, (str, int, float)) and str(x or "").strip()
            ]
            if isinstance(kps_raw, list)
            else []
        )
        return kps[:15]

    def _expand_foreach_step(self, step: PlanStep, *, kp: str) -> PlanStep:
        args = dict(getattr(step, "arguments", {}) or {})
        args["knowledge_points"] = [kp]
        title = f"{step.title}：{kp}" if kp else step.title

        thought = (getattr(step, "thought", "") or "").strip()
        if not thought:
            thought = f"执行 {step.tool}：收集并整理该知识点的学习素材。"
        if kp:
            thought = f"{thought}\n当前知识点：{kp}"

        return PlanStep(
            id=f"{step.id}-{uuid.uuid4().hex[:6]}",
            title=title,
            tool=step.tool,
            arguments=args,
            depends_on=list(getattr(step, "depends_on", []) or []),
            parallel_group=str(getattr(step, "parallel_group", "") or ""),
            thought=thought,
        )

    async def execute_step_block(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        steps: List[PlanStep],
    ) -> AsyncIterator[Dict[str, Any]]:
        async for evt in self.execution_strategy.execute_step_block(
            dispatcher=self,
            ctx=ctx,
            results=results,
            steps=steps,
        ):
            yield evt

    def _enrich_step_arguments(self, *, ctx: CompressedContext, concrete_step: PlanStep) -> None:
        """Best-effort inject `knowledge_points` into multi-point tools for better UX."""

        step_args = dict(concrete_step.arguments or {})
        export_kp = str(ctx.working_memory.get("_export_subagent_kp") or "").strip()
        if (
            export_kp
            and concrete_step.tool
            in {
                "export_study_markdown",
                "convert_markdown_to_latex",
                "refine_latex",
                "compile_latex_to_pdf",
            }
            and "knowledge_points" not in step_args
        ):
            step_args["knowledge_points"] = [export_kp]

        if (
            concrete_step.tool
            in {
                "web_search_knowledge",
                "browse_web_pages",
                "wikipedia_search",
                "mediawiki_search",
                "github_search",
                "stackexchange_search",
                "search_questions_by_knowledge",
                "aggregate_knowledge",
                "synthesize_sources",
                "detect_knowledge_type",
                "generate_outline",
                "generate_study_material",
                "critique_draft",
                "refine_draft",
                "generate_diagrams",
            }
            and "knowledge_points" not in step_args
        ):
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
                kps = [
                    str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()
                ][:15]
                if kps:
                    step_args["knowledge_points"] = kps

        concrete_step.arguments = step_args

    def _append_tool_timing(
        self,
        *,
        ctx: CompressedContext,
        concrete_step: PlanStep,
        step_result: StepResult,
        elapsed_ms: int,
    ) -> None:
        timings = ctx.working_memory.get("_tool_timings")
        if not isinstance(timings, list):
            timings = []
            ctx.working_memory["_tool_timings"] = timings
        timings.append(
            {
                "step_id": concrete_step.id,
                "name": str(concrete_step.tool or "").strip(),
                "title": str(concrete_step.title or "").strip(),
                "success": bool(step_result.success),
                "elapsed_ms": int(elapsed_ms or 0),
            }
        )

    async def execute_concrete_step(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        concrete_step: PlanStep,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Execute one step and stream SSE events (thinking/tool_call/tool_result)."""

        self._set_state(AgentState.WAITING_TOOL)
        if bool(ctx.working_memory.get("_abort_execution")):
            return

        thought = (getattr(concrete_step, "thought", "") or "").strip()
        if thought:
            yield agent_event("status", {"content": thought})

        self._enrich_step_arguments(ctx=ctx, concrete_step=concrete_step)

        yield agent_event(
            "tool_call",
            {
                "step_id": concrete_step.id,
                "name": concrete_step.tool,
                "title": concrete_step.title,
                "arguments": concrete_step.arguments,
            },
        )

        t0 = time.monotonic()
        event_queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        tool_task = asyncio.create_task(self.executor.execute_step(concrete_step, context=ctx, emit_event=event_queue.put))
        queue_task: "asyncio.Task[Dict[str, Any]]" = asyncio.create_task(event_queue.get())

        while True:
            done, _pending = await asyncio.wait({tool_task, queue_task}, return_when=asyncio.FIRST_COMPLETED)

            if queue_task in done:
                try:
                    evt = queue_task.result()
                except (asyncio.CancelledError, RuntimeError):
                    evt = None
                if isinstance(evt, dict) and evt.get("event"):
                    yield evt
                queue_task = asyncio.create_task(event_queue.get())
                continue

            if tool_task in done:
                if not queue_task.done():
                    queue_task.cancel()
                    await asyncio.gather(queue_task, return_exceptions=True)
                break

        # Drain remaining buffered events (best-effort).
        try:
            while True:
                evt = event_queue.get_nowait()
                if isinstance(evt, dict) and evt.get("event"):
                    yield evt
        except asyncio.QueueEmpty:
            pass

        step_result = await tool_task
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        self._append_tool_timing(ctx=ctx, concrete_step=concrete_step, step_result=step_result, elapsed_ms=elapsed_ms)

        yield agent_event(
            "tool_result",
            {
                "step_id": concrete_step.id,
                "name": concrete_step.tool,
                "title": concrete_step.title,
                "success": bool(step_result.success),
                "elapsed_ms": elapsed_ms,
                "output": _clip_for_sse(step_result.output),
                "error": step_result.error,
            },
        )
        results.step_results.append(step_result)
        await self.context_manager.on_step_result(ctx, step=concrete_step, result=step_result)

        try:
            async for evt in maybe_handle_step_failure(
                ctx=ctx,
                results=results,
                concrete_step=concrete_step,
                step_result=step_result,
                execute_concrete_step=self.execute_concrete_step,
            ):
                yield evt
        except StopStepExecution:
            return
        except Exception:
            logger.warning("agent_step_failure_handler_failed", exc_info=True)

        maybe_capture_markdown_artifact(step_result=step_result, results=results)

    async def ensure_planner_knowledge_points(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        user_input: str,
        profile: UserProfile,
    ) -> AsyncIterator[Dict[str, Any]]:
        split_res = ctx.working_memory.get("split_knowledge_points")
        if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
            existing = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()]
            if existing[:1]:
                return

        opts = ctx.working_memory.get("study_options")
        opts = dict(opts) if isinstance(opts, dict) else {}

        preset = str(opts.get("preset") or os.getenv("STUDY_MATERIALS_PRESET") or "").strip().lower()
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = "standard"

        split_min, split_max = 2, 8
        if preset == "quick":
            split_min, split_max = 2, 4
        elif preset == "deep":
            split_min, split_max = 4, 12
        elif preset == "research":
            split_min, split_max = 3, 8

        try:
            max_points_override = int(opts.get("max_points") or 0)
        except (TypeError, ValueError):
            max_points_override = 0
        if max_points_override > 0:
            split_max = max(1, min(max_points_override, 15))
            split_min = min(split_min, split_max)

        subject = str(profile.preferences.get("subject") or "").strip()
        split_step = PlanStep(
            id=f"split_knowledge_points-planner-{uuid.uuid4().hex[:8]}",
            title="拆分知识点",
            tool="split_knowledge_points",
            arguments={
                "topic": user_input,
                "subject": subject,
                "min_points": split_min,
                "max_points": split_max,
            },
            thought="先拆分知识点，后续才能逐点深挖并展示 SubAgent 进度。",
        )
        async for evt in self.execute_concrete_step(ctx=ctx, results=results, concrete_step=split_step):
            yield evt

        split_res = ctx.working_memory.get("split_knowledge_points")
        kps: List[str] = []
        if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
            kps = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()][:15]
        if not kps:
            return

        review_step = PlanStep(
            id=f"review_knowledge_points-planner-{uuid.uuid4().hex[:8]}",
            title="审核知识点列表",
            tool="review_knowledge_points",
            arguments={
                "topic": user_input,
                "subject": subject,
                "knowledge_points": kps,
                "min_points": split_min,
                "max_points": split_max,
            },
            thought="对拆分结果做去重、补全与粒度调整，避免过泛/重复，减少后续检索浪费。",
        )
        async for evt in self.execute_concrete_step(ctx=ctx, results=results, concrete_step=review_step):
            yield evt

    async def execute_foreach_block(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        block: List[PlanStep],
        fallback_kp: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        async for evt in self.execution_strategy.execute_foreach_block(
            dispatcher=self,
            ctx=ctx,
            results=results,
            block=block,
            fallback_kp=fallback_kp,
        ):
            yield evt

    async def execute_plan_steps(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        plan: ExecutionPlan,
        user_input: str,
        skip_export: bool,
    ) -> AsyncIterator[Dict[str, Any]]:
        steps = list(plan.steps or [])
        export_tools = {
            "export_study_markdown",
            "convert_markdown_to_latex",
            "refine_latex",
            "compile_latex_to_pdf",
        }
        export_kp = "导出：LaTeX/PDF"
        export_open = False
        export_closed = False

        i = 0
        while i < len(steps):
            if bool(ctx.working_memory.get("_abort_execution")):
                break

            step = steps[i]
            if skip_export and step.tool in export_tools:
                i += 1
                continue

            if (not export_open) and step.tool in export_tools:
                export_open = True
                async for evt in self._start_export_subagent(ctx, export_kp):
                    yield evt

            if getattr(step, "foreach_knowledge_point", False):
                block: List[PlanStep] = []
                while i < len(steps) and getattr(steps[i], "foreach_knowledge_point", False):
                    block.append(steps[i])
                    i += 1
                async for evt in self.execute_foreach_block(ctx=ctx, results=results, block=block, fallback_kp=user_input):
                    yield evt
                continue

            i += 1
            async for evt in self.execute_concrete_step(ctx=ctx, results=results, concrete_step=step):
                yield evt

            if export_open and (not export_closed) and step.tool == "compile_latex_to_pdf":
                export_closed = True
                async for evt in self._end_export_subagent(ctx, export_kp, "SubAgent 完成：导出与编译结束（LaTeX/PDF）。"):
                    yield evt

        if export_open and (not export_closed):
            export_closed = True
            async for evt in self._end_export_subagent(ctx, export_kp, "SubAgent 结束：导出流程提前终止（LaTeX/PDF）。"):
                yield evt
