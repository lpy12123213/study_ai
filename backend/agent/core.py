from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.agent.config import AgentConfig
from backend.agent.context import ContextManager
from backend.agent.executor import Executor
from backend.agent.memory import MemoryStore
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


SYSTEM_INSTRUCTIONS = """你是一位严谨的自学资料编写老师。
目标：根据学生输入的知识点，生成一份可直接自学的 Markdown 学习材料。

硬性要求：
- 输出必须是 Markdown 纯文本
- 结构清晰：知识点讲解 → 例题（含详细步骤）→ 练习题（不含答案）
- 语言：中文
- 尽量减少无依据的编造；当信息来源不足时，明确标注“推断/建议”。
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

    async def run(self, user_input: str, *, user_id: str = "anonymous") -> AsyncIterator[Dict[str, Any]]:
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
            yield agent_event("thinking", {"content": "初始化上下文…"})
            self.state = AgentState.WAITING_TOOL
            yield agent_event("tool_call", {"name": "get_user_profile", "arguments": {"user_id": user_id}})
            profile = await self.memory_store.get_user_profile(user_id=user_id)

            ctx = self.context_manager.create_context(
                user_profile=profile,
                system_instructions=SYSTEM_INSTRUCTIONS,
                current_task=user_input,
            )
            self.context_manager.append_message(ctx, role="user", content=user_input)

            for iteration in range(self.config.max_iterations):
                results = ActionResults()
                self.state = AgentState.PLANNING
                yield agent_event("thinking", {"content": f"Plan 阶段：规划（第 {iteration + 1} 轮）…"})

                plan = await self.planner.plan(topic=user_input, user_profile=profile, context=ctx, iteration=iteration)
                if plan.rationale:
                    yield agent_event("thinking", {"content": plan.rationale})

                self.state = AgentState.ACTING
                yield agent_event("thinking", {"content": "Act 阶段：执行工具链…"})

                async def _execute_concrete_step(concrete_step: PlanStep) -> AsyncIterator[Dict[str, Any]]:
                    """Execute one step and stream SSE events (thinking/tool_call/tool_result)."""

                    self.state = AgentState.WAITING_TOOL

                    thought = (getattr(concrete_step, "thought", "") or "").strip()
                    if thought:
                        yield agent_event("thinking", {"content": thought})

                    # Enrich multi-point tools with the split result for better UX (and to make
                    # downstream tools explicitly reflect the current knowledge points).
                    try:
                        step_args = dict(concrete_step.arguments or {})
                        if concrete_step.tool in {
                            "web_search_knowledge",
                            "browse_web_pages",
                            "wikipedia_search",
                            "mediawiki_search",
                            "github_search",
                            "stackexchange_search",
                            "search_questions_by_knowledge",
                            "aggregate_knowledge",
                            "generate_study_material",
                        } and "knowledge_points" not in step_args:
                            split_res = ctx.working_memory.get("split_knowledge_points")
                            if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
                                kps = [
                                    str(x or "").strip()
                                    for x in (split_res.get("knowledge_points") or [])
                                    if str(x or "").strip()
                                ][:15]
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
                    t0 = time.monotonic()
                    step_result = await self.executor.execute_step(concrete_step, context=ctx)
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
                    if (
                        step_result.success
                        and step_result.tool in {"assemble_markdown", "revise_markdown"}
                        and isinstance(step_result.output, str)
                        and step_result.output.strip()
                    ):
                        results.artifacts["markdown"] = step_result.output.strip()

                def _split_knowledge_points() -> List[str]:
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

                def _expand_foreach(step: PlanStep, *, kp: str) -> PlanStep:
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

                # DFS-style execution for `foreach_knowledge_point` blocks:
                # - BFS (old): tool-by-tool across all knowledge points
                # - DFS (new): for each knowledge point, execute the full research chain before moving on
                steps = list(plan.steps or [])
                i = 0
                while i < len(steps):
                    step = steps[i]
                    if getattr(step, "foreach_knowledge_point", False):
                        block: List[PlanStep] = []
                        while i < len(steps) and getattr(steps[i], "foreach_knowledge_point", False):
                            block.append(steps[i])
                            i += 1

                        kps = _split_knowledge_points()
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
                            for s in block:
                                async for evt in _execute_concrete_step(s):
                                    yield evt
                            continue

                        for kp in kps:
                            # Sub-agent markers (kept as "thinking" so UI can display them).
                            yield agent_event(
                                "thinking",
                                {
                                    "content": f"SubAgent 启动：深挖该知识点的资料与题型。\n当前知识点：{kp}",
                                },
                            )
                            for s in block:
                                concrete = _expand_foreach(s, kp=kp)
                                async for evt in _execute_concrete_step(concrete):
                                    yield evt
                            yield agent_event(
                                "thinking",
                                {
                                    "content": f"SubAgent 完成：已收集该知识点的资料，准备进入下一个。\n当前知识点：{kp}",
                                },
                            )
                        continue

                    i += 1
                    async for evt in _execute_concrete_step(step):
                        yield evt

                self.state = AgentState.REFLECTING
                yield agent_event("thinking", {"content": "Reflect 阶段：自检与审查…"})
                reflection = await self.reflector.reflect(topic=user_input, plan=plan, results=results, context=ctx)

                if reflection.summary:
                    yield agent_event("thinking", {"content": reflection.summary})

                if reflection.passed:
                    break

                self.state = AgentState.ITERATING
                yield agent_event(
                    "thinking",
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

            yield agent_event("thinking", {"content": "输出 Markdown…"})
            async for chunk in _chunk_text(markdown, chunk_size=600):
                yield agent_event("content", {"content": chunk, "section": "markdown"})

            self.state = AgentState.COMPRESSING
            yield agent_event("tool_call", {"name": "compress_context", "arguments": {}})
            await self.context_manager.compress_if_needed(ctx)

            yield agent_event(
                "tool_call",
                {
                    "name": "update_user_profile",
                    "arguments": {
                        "user_id": user_id,
                        "topic": user_input,
                        "passed": bool(reflection.passed) if reflection else True,
                    },
                },
            )
            await self.memory_store.record_session(
                user_id=user_id,
                topic=user_input,
                passed=bool(reflection.passed) if reflection else True,
                issues=(reflection.issues if reflection else []),
            )

            self.state = AgentState.COMPLETED
            yield agent_event(
                "done",
                {
                    "material": {
                        "topic": user_input,
                        "markdown": markdown,
                        "archive_path": archive_path,
                        "iteration": iteration + 1,
                        "passed": bool(reflection.passed) if reflection else True,
                        "issues": reflection.issues if reflection else [],
                    }
                },
            )

        except Exception as exc:  # pragma: no cover (best-effort safety)
            self.state = AgentState.ERROR
            yield agent_event("error", {"message": str(exc)})
