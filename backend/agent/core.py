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
目标：根据学生输入的主题与拆分出的知识点，生成一份可直接自学的 Markdown 学习材料。

硬性要求：
- 输出必须是 Markdown 纯文本
- 语言：中文
- 结构清晰：每个知识点以“概念讲解”为核心，配合必要的示意图（如适用），强调直观理解、关键结论、常见误区与学习建议
- 先专注概念与理解：暂时不要生成练习题/刷题内容（例题/练习题可以为空或省略）
- 不要大段照抄百科/网页原文：尽量用自己的话改写；若信息不足，明确标注“推断/建议”
- 数学公式使用 LaTeX：行内用 $...$，独立行用 $$...$$
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

    async def run(
        self,
        user_input: str,
        *,
        user_id: str = "anonymous",
        preferences: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
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
            yield agent_event("thinking", {"content": "初始化上下文…"})
            self.state = AgentState.WAITING_TOOL
            yield agent_event("tool_call", {"name": "get_user_profile", "arguments": {"user_id": user_id}})
            profile = await self.memory_store.get_user_profile(user_id=user_id)

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
            ctx.working_memory["study_options"] = dict(options) if isinstance(options, dict) else {}
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

                        yield agent_event(
                            "thinking",
                            {
                                "content": f"SubAgent 并行模式：共 {len(kps)} 个知识点，最大并发 {subagent_concurrency}。",
                            },
                        )

                        queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
                        sem = asyncio.Semaphore(subagent_concurrency)

                        async def _run_subagent(kp: str) -> None:
                            try:
                                async with sem:
                                    await queue.put(
                                        agent_event(
                                            "thinking",
                                            {
                                                "content": f"SubAgent 启动：深挖该知识点的资料与题型。\n当前知识点：{kp}",
                                            },
                                        )
                                    )
                                    for s in block:
                                        concrete = _expand_foreach(s, kp=kp)
                                        async for evt in _execute_concrete_step(concrete):
                                            await queue.put(evt)
                                    await queue.put(
                                        agent_event(
                                            "thinking",
                                            {
                                                "content": f"SubAgent 完成：已收集该知识点的资料。\n当前知识点：{kp}",
                                            },
                                        )
                                    )
                            except Exception as exc:  # pragma: no cover (best-effort safety)
                                await queue.put(
                                    agent_event(
                                        "error",
                                        {"message": f"SubAgent 运行失败（{kp}）：{exc}"},
                                    )
                                )
                            finally:
                                await queue.put(None)

                        tasks = [asyncio.create_task(_run_subagent(kp)) for kp in kps]
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
                    async for evt in _execute_concrete_step(step):
                        yield evt

                # Autonomy boost: if the heuristic reviewer says "sources insufficient", do a bounded
                # extra research pass for the failing knowledge points *within the same iteration*.
                # This avoids forcing users into a 2nd planning loop just to fetch a bit more context.
                try:
                    auto_research_raw = (os.getenv("STUDY_MATERIALS_AUTO_RESEARCH") or "1").strip().lower()
                    auto_research = auto_research_raw in {"1", "true", "yes", "y", "on"}
                except Exception:
                    auto_research = True

                if auto_research and iteration == 0 and plan:
                    review = ctx.working_memory.get("review_content")
                    if isinstance(review, dict) and review.get("passed") is False:
                        source = str(review.get("source") or "").strip().lower()
                        issues = review.get("issues")
                        if source == "heuristic" and isinstance(issues, list) and issues:
                            # Parse "知识点「...」资料来源不足" issues.
                            missing: List[str] = []
                            for it in issues:
                                s = str(it or "").strip()
                                if not s:
                                    continue
                                m = re.search(r"知识点[「“\"](.+?)[」”\"]资料来源不足", s)
                                if not m:
                                    continue
                                kp = (m.group(1) or "").strip()
                                if kp:
                                    missing.append(kp)

                            # Deduplicate while preserving order.
                            seen = set()
                            missing = [x for x in missing if not (x in seen or seen.add(x))]

                            try:
                                max_kps = int(os.getenv("STUDY_MATERIALS_AUTO_RESEARCH_MAX_POINTS") or "3")
                            except Exception:
                                max_kps = 3
                            max_kps = max(1, min(max_kps, 8))
                            missing = missing[:max_kps]

                            if missing:
                                opts = ctx.working_memory.get("study_options")
                                opts = dict(opts) if isinstance(opts, dict) else {}
                                preset = str(opts.get("preset") or "standard").strip().lower()
                                if preset not in {"quick", "standard", "deep", "research"}:
                                    preset = "standard"
                                requirements = str(opts.get("requirements") or "").strip()

                                def _env_truthy(name: str, default: bool = False) -> bool:
                                    raw = (os.getenv(name) or "").strip().lower()
                                    if not raw:
                                        return default
                                    return raw in {"1", "true", "yes", "y", "on"}

                                enable_extra_tools = bool(opts.get("enable_extra_tools")) if isinstance(opts.get("enable_extra_tools"), bool) else _env_truthy("STUDY_MATERIALS_ENABLE_EXTRA_TOOLS", False)
                                if preset in {"deep", "research"}:
                                    enable_extra_tools = True

                                subject = str(ctx.user_profile.preferences.get("subject") or "").strip()

                                yield agent_event(
                                    "thinking",
                                    {
                                        "content": "自动补检索：发现部分知识点资料不足，追加一轮研究型检索（不进入下一轮规划）…\n"
                                        + "\n".join(f"- {kp}" for kp in missing),
                                    },
                                )

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
                                        "metaso_mode": "ask",
                                        "decompose": True,
                                        "sub_questions": 4 if preset in {"deep", "research"} else 3,
                                        "preset": preset,
                                    },
                                    thought="为资料不足的知识点追加一轮研究型网搜，补齐条件/反例/推导框架等关键要素。",
                                )
                                async for evt in _execute_concrete_step(web_step):
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
                                    async for evt in _execute_concrete_step(wiki_step):
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
                                    async for evt in _execute_concrete_step(se_step):
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
                                    async for evt in _execute_concrete_step(browse_step):
                                        yield evt

                                # 3) Re-aggregate + re-generate only for missing points.
                                agg_step = PlanStep(
                                    id=f"auto-agg-{uuid.uuid4().hex[:8]}",
                                    title="自动补检索：聚合多源资料（按知识点）",
                                    tool="aggregate_knowledge",
                                    arguments={"topic": user_input, "subject": subject, "knowledge_points": missing},
                                    thought="将新增的检索结果聚合回统一素材池。",
                                )
                                async for evt in _execute_concrete_step(agg_step):
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
                                        "with_questions": bool(opts.get("with_questions")) if isinstance(opts.get("with_questions"), bool) else False,
                                        "with_diagrams": bool(opts.get("with_diagrams")) if isinstance(opts.get("with_diagrams"), bool) else True,
                                    },
                                    thought="基于补充后的资料，重写资料不足的知识点讲解。",
                                )
                                async for evt in _execute_concrete_step(gen_step):
                                    yield evt

                                assemble_step = PlanStep(
                                    id=f"auto-assemble-{uuid.uuid4().hex[:8]}",
                                    title="自动补检索：重新组装自学档案 Markdown",
                                    tool="assemble_study_archive",
                                    arguments={"topic": user_input, "subject": subject},
                                    thought="将补充后的讲解更新到最终 Markdown。",
                                )
                                async for evt in _execute_concrete_step(assemble_step):
                                    yield evt

                                # 4) Re-review so reflect phase can pass without a new planning loop.
                                review_step = PlanStep(
                                    id=f"auto-review2-{uuid.uuid4().hex[:8]}",
                                    title="自动复审（补检索后）",
                                    tool="review_content",
                                    arguments={"topic": user_input},
                                    thought="补检索后复审，确认来源覆盖已达标。",
                                )
                                async for evt in _execute_concrete_step(review_step):
                                    yield evt

                # One-shot quality: if the reviewer (LLM) finds issues, do a single auto-revise pass
                # inside the same iteration so users are less likely to hit a second planning loop.
                # We explicitly *skip* heuristic "sources不足" failures (those need more retrieval, not editing).
                try:
                    auto_revise_raw = (os.getenv("STUDY_MATERIALS_AUTO_REVISE") or "1").strip().lower()
                    auto_revise = auto_revise_raw in {"1", "true", "yes", "y", "on"}
                except Exception:
                    auto_revise = True

                if auto_revise and iteration == 0 and plan:
                    planned_tools = {str(getattr(s, "tool", "") or "") for s in (plan.steps or []) if s}
                    # If the plan already includes revise_markdown, let the planner handle it.
                    if "revise_markdown" not in planned_tools:
                        review = ctx.working_memory.get("review_content")
                        if isinstance(review, dict) and review.get("passed") is False:
                            source = str(review.get("source") or "").strip().lower()
                            issues = review.get("issues")
                            # Only apply when review is LLM-based (content/style issues).
                            if source and source != "heuristic" and isinstance(issues, list) and issues:
                                # Ensure we have something to edit.
                                markdown = str(ctx.working_memory.get("markdown") or "").strip()
                                if markdown:
                                    yield agent_event(
                                        "thinking",
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
                                    async for evt in _execute_concrete_step(revise_step):
                                        yield evt

                                    # 2) Re-run review so Reflector can pass without a new planning iteration.
                                    review_step = PlanStep(
                                        id=f"auto-review-{uuid.uuid4().hex[:8]}",
                                        title="自动复审（修订后）",
                                        tool="review_content",
                                        arguments={"topic": user_input},
                                        thought="修订后再次审查，确认问题已解决。",
                                    )
                                    async for evt in _execute_concrete_step(review_step):
                                        yield evt
                # End auto-revise

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
