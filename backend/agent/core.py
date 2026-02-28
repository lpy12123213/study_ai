from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.agent.config import AgentConfig
from backend.agent.context import ContextManager
from backend.agent.executor import Executor
from backend.agent.memory import MemoryStore
from backend.agent.policy import StudyMaterialsPolicy
from backend.agent.planner import Planner
from backend.agent.reflector import Reflector
from backend.agent.types import (
    ActionResults,
    AgentState,
    ExecutionPlan,
    PlanStep,
    ReflectionResult,
    StepResult,
    UserProfile,
    agent_event,
)


SYSTEM_INSTRUCTIONS = """你是一位经验丰富的教育专家，擅长将复杂概念拆解为可自学的清晰讲解。

【核心理念】
你遵循"费曼学习法"：如果不能用简单的语言解释清楚，说明自己还没真正理解。你的目标是让读者"恍然大悟"，而非堆砌信息。

【写作原则】
1. **先"为什么"再"是什么"**：每个概念先给出动机（为何需要它、解决什么问题），再给定义
2. **类比优先**：用日常生活或已学知识做类比，建立直觉，再过渡到严格表述
3. **渐进深入**：从最简单的情形讲起，逐步添加复杂度
4. **重点突出**：关键结论用加粗或单独成段，避免淹没在长文中
5. **误区预警**：主动指出初学者易犯的错误，说明为何会错、如何避免

【硬性要求】
- 输出格式：Markdown 纯文本（中文）
- 数学公式：行内 $...$，独立行 $$...$$
- 严禁照抄来源原文：必须用自己的语言重新组织
- 信息不足时：明确标注「推断」或「建议」
- 不输出练习题（除非明确要求）
"""


def _chunk_text(text: str, *, chunk_size: int = 500) -> AsyncIterator[str]:
    async def _gen() -> AsyncIterator[str]:
        if not text:
            return
        for i in range(0, len(text), chunk_size):
            # Cooperative scheduling so the event loop can flush SSE.
            await asyncio.sleep(0)
            yield text[i : i + chunk_size]

    return _gen()


def _clip_for_sse(value: Any, *, depth: int = 0) -> Any:
    """Best-effort trimming so tool outputs won't overwhelm SSE payloads."""

    if value is None:
        return None

    if isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        max_len = 1200 if depth == 0 else 800
        if len(value) <= max_len:
            return value
        return value[: max_len - 1].rstrip() + "…"

    if isinstance(value, list):
        if depth >= 3:
            return f"[{len(value)} items]"
        max_items = 10 if depth == 0 else 6
        clipped = [_clip_for_sse(x, depth=depth + 1) for x in value[:max_items]]
        if len(value) > max_items:
            clipped.append(f"…（共 {len(value)} 项）")
        return clipped

    if isinstance(value, dict):
        if depth >= 3:
            return "{...}"
        out: Dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            # Common large fields: keep a smaller preview.
            if key in {"markdown", "content", "stem", "solution_markdown"} and isinstance(v, str):
                out[key] = _clip_for_sse(v, depth=depth + 1)
                continue
            out[key] = _clip_for_sse(v, depth=depth + 1)
        return out

    # Fallback: stringify unknown objects (Path, datetime, etc.)
    try:
        return str(value)
    except Exception:
        return "<unserializable>"


class AgentCore:
    """Plan-Act-Reflect agent core with streaming events."""

    def __init__(
        self,
        *,
        config: Optional[AgentConfig] = None,
        memory_store: Optional[MemoryStore] = None,
        context_manager: Optional[ContextManager] = None,
        planner: Optional[Planner] = None,
        executor: Optional[Executor] = None,
        reflector: Optional[Reflector] = None,
    ) -> None:
        self.config = config or AgentConfig.from_env()
        self.memory_store = memory_store or MemoryStore()
        self.context_manager = context_manager or ContextManager(config=self.config)
        self.planner = planner or Planner(config=self.config)
        self.executor = executor or Executor(config=self.config)
        self.reflector = reflector or Reflector(config=self.config)

        self.state: AgentState = AgentState.IDLE
        # Latest context snapshot (used by resumable StudyMaterials tasks).
        self.last_context: Optional[CompressedContext] = None

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

    def _chunk_by_parallel_group(self, steps: List[PlanStep]) -> List[List[PlanStep]]:
        """Chunk contiguous steps that share the same non-empty parallel_group.

        The executor runs each chunk sequentially; chunks with len>=2 are executed concurrently.
        """

        groups: List[List[PlanStep]] = []
        i = 0
        while i < len(steps):
            pg = str(getattr(steps[i], "parallel_group", "") or "").strip()
            if not pg:
                groups.append([steps[i]])
                i += 1
                continue
            chunk: List[PlanStep] = []
            while i < len(steps):
                cur_pg = str(getattr(steps[i], "parallel_group", "") or "").strip()
                if cur_pg != pg:
                    break
                chunk.append(steps[i])
                i += 1
            groups.append(chunk)
        return groups

    async def _execute_parallel_steps(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        steps: List[PlanStep],
    ) -> AsyncIterator[Dict[str, Any]]:
        queue: "asyncio.Queue[Optional[Dict[str, Any]]]" = asyncio.Queue()

        async def _run_one(s: PlanStep) -> None:
            try:
                async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=s):
                    await queue.put(evt)
            except Exception as exc:  # pragma: no cover (best-effort safety)
                await queue.put(agent_event("error", {"message": f"Parallel step failed ({s.tool}): {exc}"}))
            finally:
                await queue.put(None)

        tasks = [asyncio.create_task(_run_one(s)) for s in steps]
        finished = 0
        while finished < len(tasks):
            item = await queue.get()
            if item is None:
                finished += 1
                continue
            yield item

        for t in tasks:
            try:
                await t
            except Exception:
                pass

    async def _execute_step_block(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        steps: List[PlanStep],
    ) -> AsyncIterator[Dict[str, Any]]:
        for chunk in self._chunk_by_parallel_group(steps):
            if bool(ctx.working_memory.get("_abort_execution")):
                return
            if len(chunk) <= 1:
                async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=chunk[0]):
                    yield evt
                continue
            async for evt in self._execute_parallel_steps(ctx=ctx, results=results, steps=chunk):
                yield evt

    async def _run_subagent(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        block: List[PlanStep],
        kp: str,
        sem: asyncio.Semaphore,
        queue: "asyncio.Queue[Optional[Dict[str, Any]]]",
    ) -> None:
        try:
            async with sem:
                await queue.put(
                    agent_event(
                        "subagent_start",
                        {
                            "knowledge_point": kp,
                            "content": f"SubAgent 启动：深挖该知识点的资料与题型。\n当前知识点：{kp}",
                        },
                    )
                )
                await queue.put(
                    agent_event(
                        "status",
                        {
                            "content": f"SubAgent 启动：深挖该知识点的资料与题型。\n当前知识点：{kp}",
                        },
                    )
                )
                concrete_block = [self._expand_foreach_step(s, kp=kp) for s in block]
                async for evt in self._execute_step_block(ctx=ctx, results=results, steps=concrete_block):
                    await queue.put(evt)
                await queue.put(
                    agent_event(
                        "subagent_end",
                        {
                            "knowledge_point": kp,
                            "content": f"SubAgent 完成：已收集该知识点的资料。\n当前知识点：{kp}",
                        },
                    )
                )
                await queue.put(
                    agent_event(
                        "status",
                        {
                            "content": f"SubAgent 完成：已收集该知识点的资料。\n当前知识点：{kp}",
                        },
                    )
                )
        except Exception as exc:  # pragma: no cover (best-effort safety)
            await queue.put(agent_event("error", {"message": f"SubAgent 运行失败（{kp}）：{exc}"}))
        finally:
            await queue.put(None)

    async def _execute_concrete_step(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        concrete_step: PlanStep,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Execute one step and stream SSE events (thinking/tool_call/tool_result)."""

        self.state = AgentState.WAITING_TOOL
        if bool(ctx.working_memory.get("_abort_execution")):
            return

        thought = (getattr(concrete_step, "thought", "") or "").strip()
        if thought:
            yield agent_event("status", {"content": thought})

        # Enrich multi-point tools with the split result for better UX (and to make
        # downstream tools explicitly reflect the current knowledge points).
        try:
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
            if concrete_step.tool in {
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
            } and "knowledge_points" not in step_args:
                split_res = ctx.working_memory.get("split_knowledge_points")
                if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
                    kps = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()][
                        :15
                    ]
                    if kps:
                        step_args["knowledge_points"] = kps
            concrete_step.arguments = step_args
        except Exception:
            # Best-effort only; never block execution.
            pass

        yield agent_event(
            "tool_call",
            {
                "step_id": concrete_step.id,
                "name": concrete_step.tool,
                "title": concrete_step.title,
                "arguments": concrete_step.arguments,
            },
        )
        # Run the tool in the background so we can stream intermediate "thinking"
        # events produced by the underlying LLM calls (OpenRouter reasoning stream).
        t0 = time.monotonic()
        event_queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()

        tool_task = asyncio.create_task(
            self.executor.execute_step(concrete_step, context=ctx, emit_event=event_queue.put)
        )
        queue_task: "asyncio.Task[Dict[str, Any]]" = asyncio.create_task(event_queue.get())

        while True:
            done, _pending = await asyncio.wait(
                {tool_task, queue_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if queue_task in done:
                try:
                    evt = queue_task.result()
                except Exception:
                    evt = None
                if isinstance(evt, dict) and evt.get("event"):
                    yield evt
                queue_task = asyncio.create_task(event_queue.get())
                continue

            if tool_task in done:
                if not queue_task.done():
                    queue_task.cancel()
                break

        # Drain any remaining buffered events (best-effort).
        try:
            while True:
                evt = event_queue.get_nowait()
                if isinstance(evt, dict) and evt.get("event"):
                    yield evt
                elif strict_llm and is_llm_error and tool_name in non_fatal_llm_tools:
                    yield agent_event(
                        "status",
                        {"content": f"Non-fatal step failed (LLM error): {tool_name}. Skipped and continuing."},
                    )
        except Exception:
            pass

        step_result = await tool_task
        elapsed_ms = int((time.monotonic() - t0) * 1000)
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
        self.context_manager.on_step_result(ctx, step=concrete_step, result=step_result)
        try:
            if not step_result.success:
                study_opts = ctx.working_memory.get("study_options")
                study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
                strict_llm = bool(study_opts.get("strict_llm"))

                tool_name = str(step_result.tool or concrete_step.tool or "").strip()
                err = str(step_result.error or "").strip()

                # LaTeX/PDF compilation can often be fixed by one more "refine LaTeX" round.
                # Do a few visible retry rounds (refine -> compile) before treating it as fatal.
                if tool_name == "compile_latex_to_pdf":
                    if not err.startswith("latex_engine_not_found"):
                        tex_current = str(ctx.working_memory.get("latex_tex") or "").strip()
                        max_rounds_raw = (
                            os.getenv("STUDY_MATERIALS_LATEX_COMPILE_ROUNDS")
                            or os.getenv("STUDY_MATERIALS_LATEX_MAX_ROUNDS")
                            or "3"
                        )
                        try:
                            max_rounds = int(max_rounds_raw)
                        except Exception:
                            max_rounds = 3
                        max_rounds = max(1, min(max_rounds, 6))

                        try:
                            cur_round = int(ctx.working_memory.get("_latex_compile_round") or 1)
                        except Exception:
                            cur_round = 1
                        cur_round = max(1, cur_round)

                        if tex_current and cur_round < max_rounds:
                            next_round = cur_round + 1
                            ctx.working_memory["_latex_compile_round"] = next_round
                            ctx.working_memory["_latex_last_compile_error"] = err

                            yield agent_event(
                                "status",
                                {"content": f"PDF 编译失败，准备第 {next_round} 轮修订与重编译…"},
                            )

                            subject_hint = str(ctx.user_profile.preferences.get("subject") or "").strip()
                            refine_step = PlanStep(
                                id=f"refine_latex-retry-{uuid.uuid4().hex[:8]}",
                                title=f"LaTeX 修订（第{next_round}轮）",
                                tool="refine_latex",
                                arguments={
                                    "topic": ctx.current_task,
                                    "subject": subject_hint,
                                    "compile_error": err,
                                },
                                thought="根据编译报错信息修订 LaTeX，提升通过率。",
                            )
                            async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=refine_step):
                                yield evt

                            compile_step = PlanStep(
                                id=f"compile_latex_to_pdf-retry-{uuid.uuid4().hex[:8]}",
                                title=f"编译 PDF（第{next_round}轮）",
                                tool="compile_latex_to_pdf",
                                arguments={"topic": ctx.current_task},
                                thought="重新编译修订后的 LaTeX，生成 PDF 下载文件。",
                            )
                            async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=compile_step):
                                yield evt
                            return

                fatal_tools = {"convert_markdown_to_latex", "refine_latex", "compile_latex_to_pdf"}
                non_fatal_llm_tools = {"generate_diagrams"}
                is_llm_error = err.startswith("llm_") or "llm_request_failed" in err or "llm_not_configured" in err
                if tool_name in fatal_tools or (strict_llm and is_llm_error and tool_name not in non_fatal_llm_tools):
                    ctx.working_memory["_abort_execution"] = True
                    ctx.working_memory["_fatal_error"] = {
                        "tool": tool_name,
                        "step_id": concrete_step.id,
                        "error": err or "unknown_error",
                    }
                    yield agent_event(
                        "status",
                        {
                            "content": f"关键步骤失败，已停止后续执行：{tool_name}\n错误：{err or 'unknown_error'}",
                        },
                    )
        except Exception:
            pass
        if (
            step_result.success
            and step_result.tool in {"assemble_markdown", "revise_markdown"}
            and isinstance(step_result.output, str)
            and step_result.output.strip()
        ):
            results.artifacts["markdown"] = step_result.output.strip()

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
            yield agent_event("status", {"content": "初始化上下文…"})
            self.state = AgentState.WAITING_TOOL
            profile_step_id = f"get_user_profile-{uuid.uuid4().hex[:8]}"
            yield agent_event(
                "tool_call",
                {
                    "step_id": profile_step_id,
                    "name": "get_user_profile",
                    "title": "读取用户画像",
                    "arguments": {"user_id": user_id},
                },
            )
            try:
                profile = await self.memory_store.get_user_profile(user_id=user_id)
                yield agent_event(
                    "tool_result",
                    {
                        "step_id": profile_step_id,
                        "name": "get_user_profile",
                        "title": "读取用户画像",
                        "success": True,
                        "output": {
                            "user_id": profile.user_id,
                            "ability_level": profile.ability_level,
                            "ability_score": profile.ability_score,
                            "preferences": dict(profile.preferences or {}),
                        },
                    },
                )
            except Exception as exc:
                yield agent_event(
                    "tool_result",
                    {
                        "step_id": profile_step_id,
                        "name": "get_user_profile",
                        "title": "读取用户画像",
                        "success": False,
                        "error": str(exc),
                    },
                )
                raise

            # Per-request overrides (e.g., subject selected in the UI). We both:
            # - apply it to this run's in-memory profile for planning/writing
            # - persist it as a user preference so later sessions keep the choice
            pref_patch: Dict[str, Any] = {}
            if isinstance(preferences, dict):
                for k, v in preferences.items():
                    key = str(k or "").strip()
                    if not key:
                        continue
                    # Ignore empty placeholders.
                    if v in (None, "", [], {}):
                        continue
                    pref_patch[key] = v
            if pref_patch:
                try:
                    profile = await self.memory_store.update_user_profile(user_id=user_id, patch=pref_patch)
                except Exception:
                    # Best-effort; never block execution.
                    try:
                        prefs = dict(profile.preferences or {})
                        prefs.update(pref_patch)
                        profile.preferences = prefs
                    except Exception:
                        pass

            ctx = self.context_manager.create_context(
                user_profile=profile,
                system_instructions=SYSTEM_INSTRUCTIONS,
                current_task=user_input,
            )
            # Study-materials behavior flags (API can override per request).
            study_opts = dict(options) if isinstance(options, dict) else {}
            if "strict_llm" not in study_opts:
                raw = str(os.getenv("STUDY_MATERIALS_STRICT_LLM") or "1").strip().lower()
                study_opts["strict_llm"] = raw in {"1", "true", "yes", "y", "on"}

            # Resume/continue: merge the previous working memory snapshot so the next iteration can
            # build on existing retrieval + drafts instead of starting from scratch.
            if isinstance(resume_working_memory, dict) and resume_working_memory:
                for k, v in resume_working_memory.items():
                    key = str(k or "").strip()
                    if not key:
                        continue
                    if key in {"study_options", "_abort_execution", "_fatal_error", "_export_subagent_kp"}:
                        continue
                    ctx.working_memory[key] = v
                # Do not carry over abort markers.
                ctx.working_memory.pop("_abort_execution", None)
                ctx.working_memory.pop("_fatal_error", None)
                ctx.working_memory.pop("_export_subagent_kp", None)

            ctx.working_memory["study_options"] = study_opts
            self.last_context = ctx
            self.context_manager.append_message(ctx, role="user", content=user_input)

            policy = StudyMaterialsPolicy()
            try:
                iter_offset = int(iteration_offset or 0)
            except Exception:
                iter_offset = 0
            iter_offset = max(0, iter_offset)

            if max_iterations is not None:
                try:
                    budget = int(max_iterations)
                except Exception:
                    budget = 0
                budget = max(1, budget)
            else:
                budget = int(policy.iteration_budget(ctx, default_cap=int(self.config.max_iterations or 1)) or 1)
                budget = max(1, budget)

            try:
                opts_for_mode = ctx.working_memory.get("study_options")
                opts_for_mode = dict(opts_for_mode) if isinstance(opts_for_mode, dict) else {}
            except Exception:
                opts_for_mode = {}
            continue_mode = str(opts_for_mode.get("continue_mode") or "").strip().lower()
            export_only = continue_mode == "fix_export"
            skip_export = continue_mode == "skip_export"

            for iteration in range(iter_offset, iter_offset + budget):
                results = ActionResults()
                self.state = AgentState.PLANNING
                yield agent_event("status", {"content": f"Plan 阶段：规划（第 {iteration + 1} 轮）…"})

                # Planner-stage: split knowledge points and do a quick review pass before planning the tool chain.
                if iteration == 0 and (not export_only):
                    split_res = ctx.working_memory.get("split_knowledge_points")
                    existing_kps: List[str] = []
                    if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
                        existing_kps = [
                            str(x or "").strip()
                            for x in (split_res.get("knowledge_points") or [])
                            if str(x or "").strip()
                        ][:15]

                    if not existing_kps:
                        try:
                            opts = ctx.working_memory.get("study_options")
                            opts = dict(opts) if isinstance(opts, dict) else {}
                        except Exception:
                            opts = {}

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
                        except Exception:
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
                        async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=split_step):
                            yield evt

                        split_res = ctx.working_memory.get("split_knowledge_points")
                        kps: List[str] = []
                        if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
                            kps = [
                                str(x or "").strip()
                                for x in (split_res.get("knowledge_points") or [])
                                if str(x or "").strip()
                            ][:15]

                        if kps:
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
                            async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=review_step):
                                yield evt

                if export_only:
                    subject = str(profile.preferences.get("subject") or "").strip()
                    compile_err = str(ctx.working_memory.get("_latex_last_compile_error") or "").strip()
                    yield agent_event(
                        "status",
                        {"content": "Continue mode: fix_export (rerun export-only steps)."},
                    )
                    plan = ExecutionPlan(
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
                else:
                    plan = await self.planner.plan(topic=user_input, user_profile=profile, context=ctx, iteration=iteration)
                if plan.rationale:
                    yield agent_event("status", {"content": plan.rationale})

                self.state = AgentState.ACTING
                yield agent_event("status", {"content": "Act 阶段：执行工具链…"})

                # DFS-style execution for `foreach_knowledge_point` blocks:
                # - BFS (old): tool-by-tool across all knowledge points
                # - DFS (new): for each knowledge point, execute the full research chain before moving on
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
                    if (
                        (not export_open)
                        and step.tool
                        in export_tools
                    ):
                        export_open = True
                        try:
                            ctx.working_memory["_export_subagent_kp"] = export_kp
                        except Exception:
                            pass
                        yield agent_event(
                            "subagent_start",
                            {
                                "knowledge_point": export_kp,
                                "content": "SubAgent 启动：导出与编译（LaTeX/PDF）。",
                            },
                        )
                        yield agent_event(
                            "status",
                            {"content": "SubAgent 启动：导出与编译（LaTeX/PDF）。"},
                        )
                    if getattr(step, "foreach_knowledge_point", False):
                        block: List[PlanStep] = []
                        while i < len(steps) and getattr(steps[i], "foreach_knowledge_point", False):
                            block.append(steps[i])
                            i += 1

                        kps = self._get_split_knowledge_points(ctx)
                        if not kps and user_input:
                            kps = [user_input]

                        # Respect the smallest positive foreach_limit in this block (if provided).
                        limits = [int(getattr(s, "foreach_limit", 0) or 0) for s in block]
                        positive_limits = [x for x in limits if x > 0]
                        limit = min(positive_limits) if positive_limits else 0
                        if limit > 0:
                            kps = kps[: max(1, limit)]

                        if not kps:
                            # Nothing to expand: execute block steps once.
                            async for evt in self._execute_step_block(ctx=ctx, results=results, steps=block):
                                yield evt
                            continue

                        subagent_concurrency = max(1, int(getattr(self.config, "subagent_concurrency", 3) or 3))
                        subagent_concurrency = min(subagent_concurrency, len(kps))
                        # Research preset tends to trigger more tool calls per knowledge point; cap concurrency
                        # to reduce rate-limit risk and improve result stability (at the cost of speed).
                        try:
                            opts = ctx.working_memory.get("study_options")
                            opts = dict(opts) if isinstance(opts, dict) else {}
                            preset = str(opts.get("preset") or "").strip().lower()
                            if preset == "research":
                                subagent_concurrency = min(subagent_concurrency, 2)
                        except Exception:
                            pass

                        if subagent_concurrency <= 1 or len(kps) <= 1:
                            for kp in kps:
                                # Sub-agent markers (separate events + status, so UI can display progress without polluting CoT).
                                yield agent_event(
                                    "subagent_start",
                                    {
                                        "knowledge_point": kp,
                                        "content": f"SubAgent 启动：深挖该知识点的资料与题型。\n当前知识点：{kp}",
                                    },
                                )
                                yield agent_event(
                                    "status",
                                    {
                                        "content": f"SubAgent 启动：深挖该知识点的资料与题型。\n当前知识点：{kp}",
                                    },
                                )
                                concrete_block = [self._expand_foreach_step(s, kp=kp) for s in block]
                                async for evt in self._execute_step_block(ctx=ctx, results=results, steps=concrete_block):
                                    yield evt
                                yield agent_event(
                                    "subagent_end",
                                    {
                                        "knowledge_point": kp,
                                        "content": f"SubAgent 完成：已收集该知识点的资料，准备进入下一个。\n当前知识点：{kp}",
                                    },
                                )
                                yield agent_event(
                                    "status",
                                    {
                                        "content": f"SubAgent 完成：已收集该知识点的资料，准备进入下一个。\n当前知识点：{kp}",
                                    },
                                )
                            continue

                        yield agent_event(
                            "status",
                            {
                                "content": f"SubAgent 并行模式：共 {len(kps)} 个知识点，最大并发 {subagent_concurrency}。",
                            },
                        )

                        queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
                        sem = asyncio.Semaphore(subagent_concurrency)
                        tasks = [
                            asyncio.create_task(
                                self._run_subagent(
                                    ctx=ctx,
                                    results=results,
                                    block=block,
                                    kp=kp,
                                    sem=sem,
                                    queue=queue,
                                )
                            )
                            for kp in kps
                        ]
                        finished = 0
                        while finished < len(tasks):
                            item = await queue.get()
                            if item is None:
                                finished += 1
                                continue
                            yield item

                        for t in tasks:
                            try:
                                await t
                            except Exception:
                                # Already surfaced via the queue as an error event.
                                pass
                        continue

                    i += 1
                    async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=step):
                        yield evt

                    if export_open and (not export_closed) and step.tool == "compile_latex_to_pdf":
                        export_closed = True
                        try:
                            ctx.working_memory.pop("_export_subagent_kp", None)
                        except Exception:
                            pass
                        yield agent_event(
                            "subagent_end",
                            {
                                "knowledge_point": export_kp,
                                "content": "SubAgent 完成：导出与编译结束（LaTeX/PDF）。",
                            },
                        )
                        yield agent_event(
                            "status",
                            {"content": "SubAgent 完成：导出与编译结束（LaTeX/PDF）。"},
                        )

                if export_open and (not export_closed):
                    export_closed = True
                    try:
                        ctx.working_memory.pop("_export_subagent_kp", None)
                    except Exception:
                        pass
                    yield agent_event(
                        "subagent_end",
                        {
                            "knowledge_point": export_kp,
                            "content": "SubAgent 结束：导出流程提前终止（LaTeX/PDF）。",
                        },
                    )
                    yield agent_event(
                        "status",
                        {"content": "SubAgent 结束：导出流程提前终止（LaTeX/PDF）。"},
                    )

                # Autonomy boost: if the heuristic reviewer says "sources insufficient" (or "dimension coverage insufficient"),
                # do a bounded extra research pass for the failing knowledge points *within the same iteration*.
                missing = policy.missing_kps_for_auto_research(ctx)
                if missing and plan:
                    policy.mark_auto_research(ctx, missing)

                    opts = ctx.working_memory.get("study_options")
                    opts = dict(opts) if isinstance(opts, dict) else {}
                    preset = str(opts.get("preset") or "standard").strip().lower()
                    if preset not in {"quick", "standard", "deep", "research"}:
                        preset = "standard"
                    requirements = str(opts.get("requirements") or "").strip()

                    enable_extra_tools: bool
                    if isinstance(opts.get("enable_extra_tools"), bool):
                        enable_extra_tools = bool(opts.get("enable_extra_tools"))
                    else:
                        raw = str(os.getenv("STUDY_MATERIALS_ENABLE_EXTRA_TOOLS") or "").strip().lower()
                        enable_extra_tools = raw in {"1", "true", "yes", "y", "on"}

                    subject = str(ctx.user_profile.preferences.get("subject") or "").strip()

                    yield agent_event(
                        "status",
                        {
                            "content": "自动补检索：发现部分知识点资料不足，追加一轮研究型检索（不进入下一轮规划）…\n"
                            + "\n".join(f"- {kp}" for kp in missing),
                        },
                    )

                    with_questions = opts.get("with_questions") if isinstance(opts.get("with_questions"), bool) else False
                    with_diagrams = opts.get("with_diagrams") if isinstance(opts.get("with_diagrams"), bool) else True

                    # 1) Extra web research (Metaso /ask + decompose).
                    web_step = PlanStep(
                        id=f"auto-web-{uuid.uuid4().hex[:8]}",
                        title="自动补检索：联网搜索知识点（研究型）",
                        tool="web_search_knowledge",
                        arguments={
                            "topic": user_input,
                            "subject": subject,
                            "knowledge_points": missing,
                            "limit": 12 if preset == "research" else 10,
                            "text_max_length": 6000,
                            "query_hint": "定义 直观理解 关键结论 适用条件 充分必要条件 等价表述 证明 推导 反例 边界情况 易错点",
                            "scope": "webpage",
                            "include_summary": True,
                            "concurrency": 3,
                            "decompose": True,
                            "sub_questions": 4 if preset in {"deep", "research"} else 3,
                            "preset": preset,
                        },
                        thought="为资料不足的知识点追加一轮研究型网搜，补齐条件/反例/推导框架等关键要素。",
                    )
                    async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=web_step):
                        yield evt

                    # 2) Optional extra tools for higher-signal sources.
                    if enable_extra_tools:
                        wiki_step = PlanStep(
                            id=f"auto-wiki-{uuid.uuid4().hex[:8]}",
                            title="自动补检索：百科检索（Wikipedia）",
                            tool="wikipedia_search",
                            arguments={
                                "topic": user_input,
                                "subject": subject,
                                "knowledge_points": missing,
                                "lang": "zh",
                                "sentences": 4,
                                "max_content_length": 2500,
                                "concurrency": 3,
                            },
                            thought="补充百科级定义/背景，提升术语一致性与可信度。",
                        )
                        async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=wiki_step):
                            yield evt

                        se_site = (
                            "math.stackexchange"
                            if ("数学" in subject or "math" in subject.lower())
                            else "stackoverflow"
                        )
                        se_step = PlanStep(
                            id=f"auto-se-{uuid.uuid4().hex[:8]}",
                            title="自动补检索：问答检索（StackExchange）",
                            tool="stackexchange_search",
                            arguments={
                                "topic": user_input,
                                "subject": subject,
                                "knowledge_points": missing,
                                "limit": 6,
                                "site": se_site,
                                "include_answers": True,
                                "query_hint": "intuition proof pitfall",
                            },
                            thought="补充高质量问答解释与易错点，增强“为什么”和“怎么用”。",
                        )
                        async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=se_step):
                            yield evt

                        browse_step = PlanStep(
                            id=f"auto-browse-{uuid.uuid4().hex[:8]}",
                            title="自动补检索：提取网页正文（节选）",
                            tool="browse_web_pages",
                            arguments={
                                "topic": user_input,
                                "subject": subject,
                                "knowledge_points": missing,
                                "top_k": 3 if preset == "research" else 2,
                                "max_chars": 14000 if preset == "research" else 12000,
                            },
                            thought="从新增检索结果中抽取可读正文片段，供写作阶段重组表达。",
                        )
                        async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=browse_step):
                            yield evt

                    # 3) Re-aggregate + re-generate only for missing points.
                    agg_step = PlanStep(
                        id=f"auto-agg-{uuid.uuid4().hex[:8]}",
                        title="自动补检索：聚合多源资料（按知识点）",
                        tool="aggregate_knowledge",
                        arguments={"topic": user_input, "subject": subject, "knowledge_points": missing},
                        thought="将新增的检索结果聚合回统一素材池。",
                    )
                    async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=agg_step):
                        yield evt

                    gen_step = PlanStep(
                        id=f"auto-gen-{uuid.uuid4().hex[:8]}",
                        title="自动补检索：生成概念讲解（按知识点）",
                        tool="generate_study_material",
                        arguments={
                            "topic": user_input,
                            "subject": subject,
                            "knowledge_points": missing,
                            "preset": preset,
                            "requirements": requirements,
                            "max_points": len(missing),
                            "max_web_results": 12 if preset == "research" else 10,
                            "max_web_pages": 3 if preset == "research" else 2,
                            "max_page_chars": 3000 if preset == "research" else 2600,
                            "with_questions": with_questions,
                            "with_diagrams": with_diagrams,
                        },
                        thought="基于补充后的资料，重写资料不足的知识点讲解。",
                    )
                    async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=gen_step):
                        yield evt

                    assemble_step = PlanStep(
                        id=f"auto-assemble-{uuid.uuid4().hex[:8]}",
                        title="自动补检索：重新组装自学档案 Markdown",
                        tool="assemble_study_archive",
                        arguments={"topic": user_input, "subject": subject},
                        thought="将补充后的讲解更新到最终 Markdown。",
                    )
                    async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=assemble_step):
                        yield evt

                    # 4) Re-review so reflect phase can pass without a new planning loop.
                    review_step = PlanStep(
                        id=f"auto-review2-{uuid.uuid4().hex[:8]}",
                        title="自动复审（补检索后）",
                        tool="review_content",
                        arguments={"topic": user_input},
                        thought="补检索后复审，确认来源覆盖已达标。",
                    )
                    async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=review_step):
                        yield evt

                # One-shot quality: if the reviewer (LLM) finds issues, do a single auto-revise pass
                # inside the same iteration so users are less likely to hit a second planning loop.
                # We explicitly *skip* heuristic "sources不足" failures (those need more retrieval, not editing).
                auto_revise = bool(policy.config.auto_revise)

                if auto_revise and plan:
                    planned_tools = {str(getattr(s, "tool", "") or "") for s in (plan.steps or []) if s}
                    # If the plan already includes revise_markdown, let the planner handle it.
                    if "revise_markdown" not in planned_tools:
                        issues = policy.issues_for_auto_revise(ctx, planned_tools=planned_tools)
                        if issues:
                            policy.mark_auto_revise(ctx)
                            markdown = str(ctx.working_memory.get("markdown") or "").strip()
                            if markdown:
                                    yield agent_event(
                                        "status",
                                        {
                                            "content": "自动修订：根据审查意见进行一次快速修订（提升一次通过率）…",
                                        },
                                    )

                                    # 1) Revise markdown
                                    revise_step = PlanStep(
                                        id=f"auto-revise-{uuid.uuid4().hex[:8]}",
                                        title="自动修订 Markdown",
                                        tool="revise_markdown",
                                        arguments={"issues": issues},
                                        thought="根据审查 issues 快速修订 Markdown（一次性修补明显问题）。",
                                    )
                                    async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=revise_step):
                                        yield evt

                                    # 2) Re-run review so Reflector can pass without a new planning iteration.
                                    review_step = PlanStep(
                                        id=f"auto-review-{uuid.uuid4().hex[:8]}",
                                        title="自动复审（修订后）",
                                        tool="review_content",
                                        arguments={"topic": user_input},
                                        thought="修订后再次审查，确认问题已解决。",
                                    )
                                    async for evt in self._execute_concrete_step(ctx=ctx, results=results, concrete_step=review_step):
                                        yield evt
                # End auto-revise

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
                self.context_manager.on_reflection(ctx, reflection)

            markdown = results.artifacts.get("markdown") or ctx.working_memory.get("markdown") or ""
            if not isinstance(markdown, str):
                markdown = ""

            archive_path = str(ctx.working_memory.get("archive_path") or "").strip()
            if not archive_path:
                saved = ctx.working_memory.get("save_markdown_file")
                if isinstance(saved, dict):
                    archive_path = str(saved.get("path") or "").strip()

            if not markdown:
                # Last-resort fallback to something readable.
                markdown = f"# 自学材料：{user_input}\n\n（生成结果为空，建议重试或提供更具体的描述）\n"

            self.state = AgentState.COMPRESSING
            compress_step_id = f"compress_context-{uuid.uuid4().hex[:8]}"
            yield agent_event(
                "tool_call",
                {
                    "step_id": compress_step_id,
                    "name": "compress_context",
                    "title": "压缩上下文",
                    "arguments": {},
                },
            )

            t0 = time.monotonic()
            try:
                before_tokens = self.context_manager.estimate_tokens(ctx)
                compress_timeout_s = float(
                    os.getenv("STUDY_MATERIALS_COMPRESS_TIMEOUT_S")
                    or os.getenv("AGENT_COMPRESS_TIMEOUT_S")
                    or "12"
                )
                compress_timeout_s = max(2.0, min(compress_timeout_s, 120.0))
                await asyncio.wait_for(
                    self.context_manager.compress_if_needed(ctx),
                    timeout=compress_timeout_s,
                )
                after_tokens = self.context_manager.estimate_tokens(ctx)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                yield agent_event(
                    "tool_result",
                    {
                        "step_id": compress_step_id,
                        "name": "compress_context",
                        "title": "压缩上下文",
                        "success": True,
                        "elapsed_ms": elapsed_ms,
                        "output": {"before_tokens": before_tokens, "after_tokens": after_tokens},
                    },
                )
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                yield agent_event(
                    "tool_result",
                    {
                        "step_id": compress_step_id,
                        "name": "compress_context",
                        "title": "压缩上下文",
                        "success": False,
                        "elapsed_ms": elapsed_ms,
                        "error": str(exc),
                    },
                )

            update_step_id = f"update_user_profile-{uuid.uuid4().hex[:8]}"
            yield agent_event(
                "tool_call",
                {
                    "step_id": update_step_id,
                    "name": "update_user_profile",
                    "title": "更新用户画像",
                    "arguments": {
                        "user_id": user_id,
                        "topic": user_input,
                        "passed": bool(reflection.passed) if reflection else True,
                    },
                },
            )

            t0 = time.monotonic()
            try:
                profile_timeout_s = float(
                    os.getenv("STUDY_MATERIALS_PROFILE_TIMEOUT_S")
                    or os.getenv("AGENT_PROFILE_TIMEOUT_S")
                    or "5"
                )
                profile_timeout_s = max(1.0, min(profile_timeout_s, 60.0))
                await asyncio.wait_for(
                    self.memory_store.record_session(
                        user_id=user_id,
                        topic=user_input,
                        passed=bool(reflection.passed) if reflection else True,
                        issues=(reflection.issues if reflection else []),
                    ),
                    timeout=profile_timeout_s,
                )
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                yield agent_event(
                    "tool_result",
                    {
                        "step_id": update_step_id,
                        "name": "update_user_profile",
                        "title": "更新用户画像",
                        "success": True,
                        "elapsed_ms": elapsed_ms,
                        "output": {
                            "user_id": user_id,
                            "topic": user_input,
                            "passed": bool(reflection.passed) if reflection else True,
                            "issues_count": len((reflection.issues if reflection else []) or []),
                        },
                    },
                )
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                yield agent_event(
                    "tool_result",
                    {
                        "step_id": update_step_id,
                        "name": "update_user_profile",
                        "title": "更新用户画像",
                        "success": False,
                        "elapsed_ms": elapsed_ms,
                        "error": str(exc),
                    },
                )

            self.state = AgentState.COMPLETED
            md_url = str(ctx.working_memory.get("md_url") or "").strip()
            pdf_url = str(ctx.working_memory.get("pdf_url") or "").strip()
            tex_url = str(ctx.working_memory.get("tex_url") or "").strip()
            md_filename = str(ctx.working_memory.get("md_filename") or "").strip()
            pdf_filename = str(ctx.working_memory.get("pdf_filename") or "").strip()
            tex_filename = str(ctx.working_memory.get("tex_filename") or "").strip()
            fatal_error = ctx.working_memory.get("_fatal_error")
            fatal_error = dict(fatal_error) if isinstance(fatal_error, dict) else None
            per_kp_report: List[Dict[str, Any]] = []
            try:
                study_opts = ctx.working_memory.get("study_options")
                study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
                with_diagrams_opt = study_opts.get("with_diagrams")
                with_diagrams = bool(with_diagrams_opt) if isinstance(with_diagrams_opt, bool) else True

                material_blob = ctx.working_memory.get("generate_study_material")
                if not isinstance(material_blob, dict):
                    material_blob = (
                        ctx.working_memory.get("study_material")
                        if isinstance(ctx.working_memory.get("study_material"), dict)
                        else {}
                    )
                sections_blob = material_blob.get("sections") if isinstance(material_blob, dict) else None
                sections_list = (
                    [s for s in (sections_blob or []) if isinstance(s, dict)] if isinstance(sections_blob, list) else []
                )

                preferred: List[str] = []
                split_res = ctx.working_memory.get("split_knowledge_points")
                if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
                    preferred = [
                        str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()
                    ][:20]
                if not preferred:
                    preferred = [
                        str(s.get("knowledge_point") or "").strip()
                        for s in sections_list
                        if str(s.get("knowledge_point") or "").strip()
                    ][:20]

                sec_by_kp: Dict[str, Dict[str, Any]] = {}
                for sec in sections_list:
                    kp = str(sec.get("knowledge_point") or "").strip()
                    if kp and kp not in sec_by_kp:
                        sec_by_kp[kp] = sec

                def _count_list(v: Any) -> int:
                    return len(v) if isinstance(v, list) else 0

                for kp in preferred:
                    sec = sec_by_kp.get(kp) or {}
                    web_results = sec.get("web_results")
                    web_pages = sec.get("web_pages")
                    gh = sec.get("github") if isinstance(sec.get("github"), dict) else {}
                    se = sec.get("stackexchange") if isinstance(sec.get("stackexchange"), dict) else {}

                    usage = sec.get("explanation_usage") if isinstance(sec.get("explanation_usage"), dict) else {}
                    try:
                        total_tokens = int(usage.get("total_tokens") or 0)
                    except Exception:
                        total_tokens = 0
                    try:
                        conts = int(sec.get("explanation_continuations") or 0)
                    except Exception:
                        conts = 0
                    finish_reason = str(sec.get("explanation_finish_reason") or "").strip().lower()

                    diagram = sec.get("diagram") if isinstance(sec.get("diagram"), dict) else {}
                    has_diagram = bool(str(diagram.get("url") or diagram.get("markdown") or "").strip())

                    missing: List[str] = []
                    if _count_list(web_results) < 2:
                        missing.append("web_results_low")
                    if _count_list(web_pages) == 0:
                        missing.append("web_pages_missing")
                    if finish_reason == "length" or conts > 0:
                        missing.append("llm_truncated")
                    if with_diagrams and not has_diagram:
                        missing.append("diagram_missing")

                    per_kp_report.append(
                        {
                            "knowledge_point": kp,
                            "web_results": _count_list(web_results),
                            "web_pages": _count_list(web_pages),
                            "github_results": _count_list(gh.get("results")),
                            "stackexchange_results": _count_list(se.get("results")),
                            "tokens_total": total_tokens,
                            "continuations": conts,
                            "missing": missing,
                        }
                    )
            except Exception:
                per_kp_report = []
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
                },
            )

        except Exception as exc:  # pragma: no cover (best-effort safety)
            self.state = AgentState.ERROR
            yield agent_event("error", {"message": str(exc)})
