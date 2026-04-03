from __future__ import annotations

import os
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.agent.types import ActionResults, CompressedContext, ExecutionPlan, PlanStep, agent_event


def auto_research_context(*, ctx: CompressedContext, user_input: str) -> Dict[str, Any]:
    try:
        opts = ctx.working_memory.get("study_options")
        opts = dict(opts) if isinstance(opts, dict) else {}
    except Exception:
        opts = {}

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
    with_questions = bool(opts.get("with_questions")) if isinstance(opts.get("with_questions"), bool) else False
    with_diagrams = bool(opts.get("with_diagrams")) if isinstance(opts.get("with_diagrams"), bool) else True

    return {
        "preset": preset,
        "requirements": requirements,
        "enable_extra_tools": enable_extra_tools,
        "subject": subject,
        "with_questions": with_questions,
        "with_diagrams": with_diagrams,
        "topic": user_input,
    }


async def auto_research_retrieve(
    *,
    ctx: CompressedContext,
    results: ActionResults,
    missing: List[str],
    cfg: Dict[str, Any],
    execute_concrete_step: Any,
) -> AsyncIterator[Dict[str, Any]]:
    preset = str(cfg.get("preset") or "standard")
    subject = str(cfg.get("subject") or "")
    topic = str(cfg.get("topic") or "")

    web_step = PlanStep(
        id=f"auto-web-{uuid.uuid4().hex[:8]}",
        title="自动补检索：联网搜索知识点（研究型）",
        tool="web_search_knowledge",
        arguments={
            "topic": topic,
            "subject": subject,
            "knowledge_points": missing,
            "limit": 12 if preset == "research" else 10,
            "text_max_length": 6000,
            "query_hint": "定义 直观理解 关键结论 适用条件 充分必要条件 等价表述 证明 推导 反例 边界情况 易错点",
            "scope": "webpage",
            "include_summary": False,
            "concurrency": 3,
            "decompose": True,
            "sub_questions": 4 if preset in {"deep", "research"} else 3,
            "preset": preset,
        },
        thought="为资料不足的知识点追加一轮研究型网搜，补齐条件/反例/推导框架等关键要素。",
    )
    async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=web_step):
        yield evt

    if not bool(cfg.get("enable_extra_tools")):
        return

    wiki_step = PlanStep(
        id=f"auto-wiki-{uuid.uuid4().hex[:8]}",
        title="自动补检索：百科检索（Wikipedia）",
        tool="wikipedia_search",
        arguments={
            "topic": topic,
            "subject": subject,
            "knowledge_points": missing,
            "lang": "zh",
            "sentences": 4,
            "max_content_length": 2500,
            "concurrency": 3,
        },
        thought="补充百科级定义/背景，提升术语一致性与可信度。",
    )
    async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=wiki_step):
        yield evt

    se_site = "math.stackexchange" if ("数学" in subject or "math" in subject.lower()) else "stackoverflow"
    se_step = PlanStep(
        id=f"auto-se-{uuid.uuid4().hex[:8]}",
        title="自动补检索：问答检索（StackExchange）",
        tool="stackexchange_search",
        arguments={
            "topic": topic,
            "subject": subject,
            "knowledge_points": missing,
            "limit": 6,
            "site": se_site,
            "include_answers": True,
            "query_hint": "intuition proof pitfall",
        },
        thought="补充高质量问答解释与易错点，增强“为什么”和“怎么用”。",
    )
    async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=se_step):
        yield evt

    browse_step = PlanStep(
        id=f"auto-browse-{uuid.uuid4().hex[:8]}",
        title="自动补检索：提取网页正文（节选）",
        tool="browse_web_pages",
        arguments={
            "topic": topic,
            "subject": subject,
            "knowledge_points": missing,
            "top_k": 3 if preset == "research" else 2,
            "max_chars": 14000 if preset == "research" else 12000,
        },
        thought="从新增检索结果中抽取可读正文片段，供写作阶段重组表达。",
    )
    async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=browse_step):
        yield evt


async def auto_research_regenerate(
    *,
    ctx: CompressedContext,
    results: ActionResults,
    missing: List[str],
    cfg: Dict[str, Any],
    execute_concrete_step: Any,
) -> AsyncIterator[Dict[str, Any]]:
    preset = str(cfg.get("preset") or "standard")
    subject = str(cfg.get("subject") or "")
    topic = str(cfg.get("topic") or "")
    requirements = str(cfg.get("requirements") or "")
    with_questions = bool(cfg.get("with_questions"))
    with_diagrams = bool(cfg.get("with_diagrams"))

    agg_step = PlanStep(
        id=f"auto-agg-{uuid.uuid4().hex[:8]}",
        title="自动补检索：聚合多源资料（按知识点）",
        tool="aggregate_knowledge",
        arguments={"topic": topic, "subject": subject, "knowledge_points": missing},
        thought="将新增的检索结果聚合回统一素材池。",
    )
    async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=agg_step):
        yield evt

    gen_step = PlanStep(
        id=f"auto-gen-{uuid.uuid4().hex[:8]}",
        title="自动补检索：生成概念讲解（按知识点）",
        tool="generate_study_material",
        arguments={
            "topic": topic,
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
    async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=gen_step):
        yield evt

    assemble_step = PlanStep(
        id=f"auto-assemble-{uuid.uuid4().hex[:8]}",
        title="自动补检索：重新组装自学档案 Markdown",
        tool="assemble_study_archive",
        arguments={"topic": topic, "subject": subject},
        thought="将补充后的讲解更新到最终 Markdown。",
    )
    async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=assemble_step):
        yield evt

    review_step = PlanStep(
        id=f"auto-review2-{uuid.uuid4().hex[:8]}",
        title="自动复审（补检索后）",
        tool="review_content",
        arguments={"topic": topic},
        thought="补检索后复审，确认来源覆盖已达标。",
    )
    async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=review_step):
        yield evt


async def maybe_auto_research(
    *,
    ctx: CompressedContext,
    results: ActionResults,
    plan: Optional[ExecutionPlan],
    policy: Any,
    user_input: str,
    execute_concrete_step: Any,
) -> AsyncIterator[Dict[str, Any]]:
    missing = policy.missing_kps_for_auto_research(ctx)
    if not missing or not plan:
        return

    policy.mark_auto_research(ctx, missing)
    cfg = auto_research_context(ctx=ctx, user_input=user_input)

    yield agent_event(
        "status",
        {
            "content": "自动补检索：发现部分知识点资料不足，追加一轮研究型检索（不进入下一轮规划）…\n"
            + "\n".join(f"- {kp}" for kp in missing),
        },
    )

    async for evt in auto_research_retrieve(
        ctx=ctx,
        results=results,
        missing=missing,
        cfg=cfg,
        execute_concrete_step=execute_concrete_step,
    ):
        yield evt

    async for evt in auto_research_regenerate(
        ctx=ctx,
        results=results,
        missing=missing,
        cfg=cfg,
        execute_concrete_step=execute_concrete_step,
    ):
        yield evt


async def maybe_auto_revise(
    *,
    ctx: CompressedContext,
    results: ActionResults,
    plan: Optional[ExecutionPlan],
    policy: Any,
    execute_concrete_step: Any,
) -> AsyncIterator[Dict[str, Any]]:
    if not bool(policy.config.auto_revise) or not plan:
        return

    planned_tools = {str(getattr(s, "tool", "") or "") for s in (plan.steps or []) if s}
    if "revise_markdown" in planned_tools:
        return

    issues = policy.issues_for_auto_revise(ctx, planned_tools=planned_tools)
    if not issues:
        return

    policy.mark_auto_revise(ctx)
    markdown = str(ctx.working_memory.get("markdown") or "").strip()
    if not markdown:
        return

    yield agent_event("status", {"content": "自动修订：根据审查意见进行一次快速修订（提升一次通过率）…"})

    revise_step = PlanStep(
        id=f"auto-revise-{uuid.uuid4().hex[:8]}",
        title="自动修订 Markdown",
        tool="revise_markdown",
        arguments={"issues": issues},
        thought="根据审查 issues 快速修订 Markdown（一次性修补明显问题）。",
    )
    async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=revise_step):
        yield evt

    review_step = PlanStep(
        id=f"auto-review-{uuid.uuid4().hex[:8]}",
        title="自动复审（修订后）",
        tool="review_content",
        arguments={"topic": ctx.current_task},
        thought="修订后再次审查，确认问题已解决。",
    )
    async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=review_step):
        yield evt

