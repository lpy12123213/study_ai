from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict, List, Optional

from backend.agent.config import AgentConfig
from backend.agent.types import CompressedContext, ExecutionPlan, PlanStep, UserProfile
from backend.core.llm_client import chat_completion_text
from backend.core.settings import (
    DEFAULT_SUBJECT,
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_MAX_TOKENS,
    LESSON_PLAN_TEMPERATURE,
    MOONSHOT_API_KEY,
)


def _env_truthy(name: str) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


_CORE_TOOLS: Dict[str, str] = {
    "split_knowledge_points": "把主题拆成多个可检索子知识点（输出 knowledge_points 列表）",
    "review_knowledge_points": "审核并微调知识点列表（去重/补全/粒度调整）",
    "web_search_knowledge": "联网搜索知识点（Exa 优先；deep/research 可启用 deepresearch 多轮；Metaso/智谱兜底；返回 results 列表 + 可选 summary）",
    "aggregate_knowledge": "聚合：拆分 + 网搜 + 题库（可选：百科/网页正文/问答/GitHub）",
    "synthesize_sources": "源简报：对聚合素材去噪/提炼关键事实/结构化为 writer 友好的 source_brief（写入 source_briefs）",
    "detect_knowledge_type": "知识类型检测：definition/theorem/algorithm/...（写入 knowledge_types）",
    "generate_outline": "生成自适应写作大纲：基于 knowledge_type + source_brief（写入 outlines）",
    "generate_study_material": "生成概念讲解（基于 source_brief + outline；section 级并行写作）",
    "critique_draft": "自我批判：对草稿多维度打分并给出定向修订指令（写入 critiques）",
    "refine_draft": "精炼修订：根据 critique 指令对草稿做定向修改（高分可自动跳过）",
    "generate_diagrams": "生成配图：为知识点规划并渲染教学示意图（TikZ/Seedream），结果写入 diagrams",
    "assemble_study_archive": "组装最终 Markdown（自学档案）",
    "revise_markdown": "按审查问题修订 Markdown（可选）",
    "save_markdown_file": "保存 Markdown 到文件",
    "export_study_markdown": "将最终 Markdown 发布为可下载文件（返回 md_url）",
    "convert_markdown_to_latex": "用 LLM 把 Markdown 转成 ElegantBook LaTeX（返回 tex_url）",
    "refine_latex": "对 LaTeX 做二次修订（结构/公式/图片/编译友好性）",
    "compile_latex_to_pdf": "编译 LaTeX 为 PDF（返回 pdf_url）",
    "review_content": "内容审查（结构/完整性/可靠性）",
}

_DRAW_TOOLS: Dict[str, str] = {
    "tikz_to_svg": "使用 LaTeX TikZ 编译生成 SVG 矢量图",
    "seedream_generate": "使用火山云 Seedream 4.5（ARK images/generations）根据自然语言生成图片",
}

_QUESTION_TOOLS: Dict[str, str] = {
    "search_questions_by_knowledge": "题库按知识点搜题（例题+练习题）（默认关闭；可用 STUDY_MATERIALS_ENABLE_QUESTIONS=1 开启）",
}

_EXTRA_TOOLS: Dict[str, str] = {
    "wikipedia_search": "Wikipedia 百科检索（中文）",
    "mediawiki_search": "MediaWiki 百科检索（可用于 Wikipedia/Wikibooks/ProofWiki 等）",
    "stackexchange_search": "StackExchange 问答检索（高质量解释与典型问题）",
    "github_search": "GitHub 仓库检索（笔记/教程/代码示例等）",
    "browse_web_pages": "Browse and extract page text (best-effort)",
}

def _build_allowed_tools(*, enable_questions: bool, enable_extra_tools: bool, enable_diagrams: bool) -> Dict[str, str]:
    tools: Dict[str, str] = dict(_CORE_TOOLS)
    if enable_diagrams:
        tools.update(_DRAW_TOOLS)
    if enable_questions:
        tools.update(_QUESTION_TOOLS)
    if enable_extra_tools:
        tools.update(_EXTRA_TOOLS)
    return tools


def _normalize_preset(value: str) -> str:
    """Normalize study-materials presets.

    Supported:
    - quick: shorter, fewer sources, faster
    - standard: default
    - deep: deeper retrieval + longer explanations
    - research: more research-oriented (multi-pass retrieval + deeper synthesis)
    """

    v = (value or "").strip().lower()
    if v in {"quick", "fast", "brief"}:
        return "quick"
    if v in {"research", "deepresearch", "deep-research", "researchy"}:
        return "research"
    if v in {"deep", "detail", "detailed"}:
        return "deep"
    if v in {"standard", "normal", "default"}:
        return "standard"
    return ""


def _study_options_from_context(context: CompressedContext) -> Dict[str, Any]:
    opts = context.working_memory.get("study_options")
    return dict(opts) if isinstance(opts, dict) else {}


def _study_flags(context: CompressedContext) -> Dict[str, Any]:
    """Compute study-materials feature flags from env + per-task options."""

    opts = _study_options_from_context(context)
    preset = _normalize_preset(str(opts.get("preset") or os.getenv("STUDY_MATERIALS_PRESET") or ""))

    with_q = opts.get("with_questions")
    enable_questions = bool(with_q) if isinstance(with_q, bool) else _env_truthy("STUDY_MATERIALS_ENABLE_QUESTIONS")

    extra = opts.get("enable_extra_tools")
    enable_extra_tools = bool(extra) if isinstance(extra, bool) else _env_truthy("STUDY_MATERIALS_ENABLE_EXTRA_TOOLS")

    # Deep preset does not auto-enable extra tools by default
    # if preset in {"deep", "research"}:
    #     enable_extra_tools = True

    with_diagrams = opts.get("with_diagrams")
    enable_diagrams = bool(with_diagrams) if isinstance(with_diagrams, bool) else True

    max_points = opts.get("max_points")
    try:
        max_points_int = int(max_points) if max_points is not None else 0
    except Exception:
        max_points_int = 0

    return {
        "preset": preset or "standard",
        "enable_questions": enable_questions,
        "enable_extra_tools": enable_extra_tools,
        "enable_diagrams": enable_diagrams,
        "max_points": max_points_int,
        "requirements": str(opts.get("requirements") or "").strip(),
    }


def _difficulty_from_profile(profile: UserProfile) -> str:
    score = float(profile.ability_score or 0.5)
    if score < 0.4:
        return "简单"
    if score < 0.7:
        return "中等"
    return "困难"


def _extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


class Planner:
    def __init__(self, *, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_env()

    async def _call_planner_llm(self, *, messages: List[Dict[str, str]], max_tokens: int = 6000) -> str:
        normalized_model = str(self.config.planner_model or "").strip()
        if not normalized_model:
            return ""

        # Planner calls are user-facing latency bottlenecks. Some providers may occasionally hang
        # until the global HTTP timeout (API_TIMEOUT). Use a smaller dedicated timeout so we can
        # quickly fall back to the deterministic plan and keep the UI progressing.
        timeout_raw = (
            os.getenv("STUDY_MATERIALS_PLANNER_TIMEOUT_S")
            or os.getenv("AGENT_PLANNER_TIMEOUT_S")
            or os.getenv("LESSON_PLAN_PLANNER_TIMEOUT_S")
            or ""
        ).strip()
        try:
            timeout_s = float(timeout_raw) if timeout_raw else 30.0
        except Exception:
            timeout_s = 30.0
        timeout_s = max(10.0, min(timeout_s, 300.0))

        try:
            return await asyncio.wait_for(
                chat_completion_text(
                    messages=messages,
                    model=normalized_model,
                    temperature=float(LESSON_PLAN_TEMPERATURE or 0.4),
                    max_tokens=int(max_tokens or LESSON_PLAN_MAX_TOKENS or 1400),
                    retries=3,
                    req_id_prefix="planner",
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            return ""
        except Exception:
            return ""

    def _fallback_plan(
        self,
        *,
        topic: str,
        subject: str,
        difficulty: str,
        iteration: int,
        issues: Optional[List[str]],
        flags: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        def sid(prefix: str) -> str:
            return f"{prefix}-{iteration}-{uuid.uuid4().hex[:8]}"

        flags = flags if isinstance(flags, dict) else {}
        preset = str(flags.get("preset") or "standard").strip().lower() or "standard"
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = "standard"

        use_questions = bool(flags.get("enable_questions")) if "enable_questions" in flags else _env_truthy("STUDY_MATERIALS_ENABLE_QUESTIONS")
        enable_extra_tools = bool(flags.get("enable_extra_tools")) if "enable_extra_tools" in flags else _env_truthy("STUDY_MATERIALS_ENABLE_EXTRA_TOOLS")
        enable_diagrams = bool(flags.get("enable_diagrams")) if "enable_diagrams" in flags else True
        requirements = str(flags.get("requirements") or "").strip()
        max_points_override = 0
        try:
            max_points_override = int(flags.get("max_points") or 0)
        except Exception:
            max_points_override = 0

        # Preset defaults (balance quality/speed). These can still be overridden per-task via flags.
        split_min = 2
        split_max = 8
        web_limit = 12
        sub_questions = 6  # how many (decomposed) sub-questions per knowledge point
        max_web_pages = 2
        if preset == "quick":
            split_min, split_max = 2, 4
            web_limit = 8
            sub_questions = 4
            max_web_pages = 1
        elif preset == "deep":
            split_min, split_max = 4, 12
            web_limit = 14
            sub_questions = 10
            max_web_pages = 3
            # Deep preset does not auto-enable extra tools by default
            # enable_extra_tools = True  # deep implies richer retrieval
        elif preset == "research":
            # Research mode: fewer points but deeper per-point retrieval + synthesis.
            split_min, split_max = 3, 8
            web_limit = 16
            sub_questions = 12
            max_web_pages = 4
            # Research preset does not auto-enable extra tools by default
            # enable_extra_tools = True

        if max_points_override > 0:
            split_max = max(1, min(max_points_override, 15))
            split_min = min(split_min, split_max)

        # Research-style multi-pass web search: keep each pass focused so results are diverse and
        # downstream synthesis is easier (and less copy-pastey).
        sub_q_pass1 = sub_questions
        sub_q_pass2 = max(4, min(sub_questions, 6))
        sub_q_pass3 = max(4, min(sub_questions, 6))
        if preset in {"deep", "research"}:
            # Prefer 2-3 focused passes to increase diversity and keep each ask answerable.
            sub_q_pass1 = max(4, min(sub_questions, 6))

        steps: List[PlanStep] = [
            PlanStep(
                id=sid("web_search_knowledge"),
                title="联网搜索知识点（报告型摘要）",
                tool="web_search_knowledge",
                arguments={
                    "topic": topic,
                    "subject": subject,
                    "limit": web_limit,
                    "text_max_length": 6000,
                    "query_hint": "定义 概念 直观理解 性质 定理 证明 误区 应用",
                    "scope": "webpage",
                    "include_summary": True,
                    "concurrency": 3,
                    # SubAgent behavior: decompose the knowledge point into smaller questions before asking.
                    "decompose": True,
                    # SubAgent behavior: decompose -> ask. This improves quality and reduces "one big ask".
                    "sub_questions": sub_q_pass1,
                    "preset": preset,
                },
                foreach_knowledge_point=True,
                thought="为每个知识点检索可用讲解资料，并获取一段 summary 作为“报告型梳理”（概念为主）。",
            ),
        ]

        # Deep/Research preset: do extra focused web passes to improve coverage and reduce hallucination.
        if preset in {"deep", "research"}:
            steps.append(
                PlanStep(
                    id=sid("web_search_knowledge_proof"),
                    title="联网搜索知识点（条件/反例/推导）",
                    tool="web_search_knowledge",
                    arguments={
                        "topic": topic,
                        "subject": subject,
                        "limit": min(10, web_limit),
                        "text_max_length": 6000,
                        "query_hint": "充分必要条件 等价表述 证明 推导 反例 边界条件 易错点 常见错误",
                        "scope": "webpage",
                        "include_summary": True,
                        "concurrency": 3,
                        "decompose": True,
                        "sub_questions": sub_q_pass2,
                        "preset": preset,
                    },
                    foreach_knowledge_point=True,
                    thought="第二轮网搜：补齐使用条件/边界情况/反例与推导思路，增强严谨性与可迁移性。",
                )
            )

        if preset == "research":
            steps.append(
                PlanStep(
                    id=sid("web_search_knowledge_apply"),
                    title="联网搜索知识点（应用/典型问题）",
                    tool="web_search_knowledge",
                    arguments={
                        "topic": topic,
                        "subject": subject,
                        "limit": min(10, web_limit),
                        "text_max_length": 6000,
                        "query_hint": "应用场景 典型问题 常见问法 直观图像 题型 关键步骤",
                        "scope": "webpage",
                        "include_summary": True,
                        "concurrency": 3,
                        "decompose": True,
                        "sub_questions": sub_q_pass3,
                        "preset": preset,
                    },
                    foreach_knowledge_point=True,
                    thought="第三轮网搜：补充应用与典型问题表述，确保“学完能用”。",
                )
            )

        if enable_extra_tools:
            # Extra sources: better variety and deeper understanding. Kept optional for stability/perf.
            se_site = "math.stackexchange" if ("数学" in subject or "math" in subject.lower()) else "stackoverflow"
            steps.extend(
                [
                    PlanStep(
                        id=sid("wikipedia_search"),
                        title="百科检索（Wikipedia）",
                        tool="wikipedia_search",
                        arguments={"topic": topic, "subject": subject, "lang": "zh", "sentences": 4, "max_content_length": 2500},
                        foreach_knowledge_point=True,
                        thought="补充百科级定义与背景，便于建立直观框架。",
                    ),
                    PlanStep(
                        id=sid("mediawiki_search"),
                        title="百科检索（MediaWiki）",
                        tool="mediawiki_search",
                        # Prefer Wikibooks as a "textbook-like" source; still MediaWiki API.
                        arguments={
                            "topic": topic,
                            "subject": subject,
                            "project": "wikibooks",
                            "lang": "zh",
                            "sentences": 4,
                            "max_content_length": 2500,
                        },
                        foreach_knowledge_point=True,
                        thought="补充 Wikibooks/ProofWiki 等来源的结构化内容（如可用）。",
                    ),
                    PlanStep(
                        id=sid("stackexchange_search"),
                        title="问答检索（StackExchange）",
                        tool="stackexchange_search",
                        arguments={
                            "topic": topic,
                            "subject": subject,
                            "limit": 4 if preset == "quick" else 6,
                            "site": se_site,
                            "include_answers": True,
                            "query_hint": "intuition proof pitfall",
                        },
                        foreach_knowledge_point=True,
                        thought="补充高质量问答解释与易错点，提升可理解性。",
                    ),
                    PlanStep(
                        id=sid("github_search"),
                        title="代码/笔记检索（GitHub）",
                        tool="github_search",
                        arguments={"topic": topic, "subject": subject, "limit": 5, "include_readme": False},
                        foreach_knowledge_point=True,
                        thought="查找教程/笔记仓库，获取更接近“教学表达”的材料线索。",
                    ),
                    PlanStep(
                        id=sid("browse_web_pages"),
                        title="提取网页正文（节选）",
                        tool="browse_web_pages",
                        arguments={"topic": topic, "subject": subject, "top_k": 2 if preset != "quick" else 1, "max_chars": 12000},
                        foreach_knowledge_point=True,
                        thought="从检索结果中抽取可读正文片段，用于写作阶段重组表达。",
                    ),
                ]
            )

        if use_questions:
            steps.append(
                PlanStep(
                    id=sid("search_questions_by_knowledge"),
                    title="题库按知识点检索（例题+练习题）",
                    tool="search_questions_by_knowledge",
                    arguments={
                        "topic": topic,
                        "subject": subject,
                        "difficulty": difficulty,
                        "examples_limit": 1,
                        "exercises_limit": 6,
                        "max_pages": 3,
                    },
                    foreach_knowledge_point=True,
                    thought="（可选）为每个知识点搜集例题与练习题；默认关闭以优先保证概念质量。",
                )
            )

        steps.extend(
            [
                PlanStep(
                    id=sid("aggregate_knowledge"),
                    title="聚合多源资料（按知识点）",
                    tool="aggregate_knowledge",
                    arguments={"topic": topic, "subject": subject},
                    foreach_knowledge_point=True,
                    thought="把网搜/题库结果按知识点聚合，形成可用于写作的统一素材。",
                ),
                PlanStep(
                    id=sid("synthesize_sources"),
                    title="综合源简报（按知识点）",
                    tool="synthesize_sources",
                    arguments={
                        "topic": topic,
                        "subject": subject,
                        "max_web_results": 10 if preset == "quick" else 12 if preset == "standard" else 14,
                        "max_web_pages": max_web_pages,
                        "max_page_chars": 2600 if preset != "research" else 3200,
                    },
                    foreach_knowledge_point=True,
                    parallel_group="kp_prewrite",
                    thought="对聚合素材去噪并提炼关键事实，生成结构化「源简报」，降低后续写作噪声与上下文长度。",
                ),
                PlanStep(
                    id=sid("detect_knowledge_type"),
                    title="检测知识类型（按知识点）",
                    tool="detect_knowledge_type",
                    arguments={"topic": topic, "subject": subject},
                    foreach_knowledge_point=True,
                    parallel_group="kp_prewrite",
                    thought="判断知识点类型（定义/定理/算法等），为后续自适应大纲与写作提供结构先验。",
                ),
                PlanStep(
                    id=sid("generate_outline"),
                    title="生成自适应大纲（按知识点）",
                    tool="generate_outline",
                    arguments={"topic": topic, "subject": subject, "preset": preset, "requirements": requirements},
                    foreach_knowledge_point=True,
                    thought="基于知识类型与源简报生成写作大纲（含验证标准），为分段并行写作做准备。",
                ),
                PlanStep(
                    id=sid("generate_study_material"),
                    title="生成概念讲解（按知识点）",
                    tool="generate_study_material",
                    arguments={
                        "topic": topic,
                        "subject": subject,
                        "preset": preset,
                        "requirements": requirements,
                        "max_examples": 1 if use_questions else 0,
                        "max_points": 1,
                        "max_web_results": 15 if preset == "research" else 12 if preset == "deep" else 10,
                        # Keep context compact to avoid LLM call failures (context overflow) and improve speed.
                        "max_web_pages": max_web_pages,
                        "max_page_chars": 3200 if preset == "research" else 2600,
                        "with_questions": bool(use_questions),
                        # Diagrams are generated in a separate parallel stage (generate_diagrams).
                        "with_diagrams": False,
                    },
                    foreach_knowledge_point=True,
                    thought="按大纲对当前知识点进行分段并行写作，生成可直接自学的核心讲解草稿。",
                ),
                PlanStep(
                    id=sid("critique_draft"),
                    title="自我批判（按知识点）",
                    tool="critique_draft",
                    arguments={"topic": topic, "subject": subject},
                    foreach_knowledge_point=True,
                    parallel_group="kp_postwrite",
                    thought="对草稿做多维度审查（准确性/清晰度/完整性/原创性/深度匹配），给出可执行修订指令。",
                ),
                *(
                    [
                        PlanStep(
                            id=sid("generate_diagrams"),
                            title="生成教学配图（按知识点）",
                            tool="generate_diagrams",
                            arguments={"topic": topic, "subject": subject, "preset": preset},
                            foreach_knowledge_point=True,
                            parallel_group="kp_postwrite",
                            thought="为该知识点生成必要的示意图（与自我批判并行），帮助直观理解。",
                        )
                    ]
                    if enable_diagrams
                    else []
                ),
                PlanStep(
                    id=sid("refine_draft"),
                    title="精炼修订（按知识点）",
                    tool="refine_draft",
                    arguments={"topic": topic, "subject": subject},
                    foreach_knowledge_point=True,
                    thought="根据批判意见对草稿做定向修订（高分则自动跳过）。",
                ),
                PlanStep(
                    id=sid("assemble_study_archive"),
                    title="组装自学档案 Markdown",
                    tool="assemble_study_archive",
                    arguments={"topic": topic, "subject": subject},
                    thought="将生成内容整理成结构化 Markdown：讲解（含示意图）→ 资料来源。",
                ),
            ]
        )

        if iteration > 0 and issues:
            steps.append(
                PlanStep(
                    id=sid("revise_markdown"),
                    title="根据审查问题修订 Markdown",
                    tool="revise_markdown",
                    arguments={"issues": issues},
                    thought="根据自检发现的问题修订内容，提升完整性与可读性。",
                )
            )

        steps.extend(
            [
                PlanStep(
                    id=sid("save_markdown_file"),
                    title="保存 Markdown 到文件",
                    tool="save_markdown_file",
                    arguments={"topic": topic, "dir": "study_archives"},
                    thought="把最终结果保存为本地 Markdown 文件，便于复习与分享。",
                ),
                PlanStep(
                    id=sid("export_study_markdown"),
                    title="导出 Markdown 下载文件",
                    tool="export_study_markdown",
                    arguments={"topic": topic},
                    thought="将最终 Markdown 发布为可下载链接，前端仅展示下载入口而不直接渲染全文。",
                ),
                PlanStep(
                    id=sid("convert_markdown_to_latex"),
                    title="Markdown → LaTeX（ElegantBook）",
                    tool="convert_markdown_to_latex",
                    arguments={"topic": topic, "subject": subject},
                    thought="使用 LLM 将 Markdown 转为 ElegantBook LaTeX，为编译 PDF 做准备。",
                ),
                PlanStep(
                    id=sid("refine_latex"),
                    title="LaTeX 二次修订",
                    tool="refine_latex",
                    arguments={"topic": topic, "subject": subject},
                    thought="对 LaTeX 进行二次修订，尽量减少编译失败与排版问题。",
                ),
                PlanStep(
                    id=sid("compile_latex_to_pdf"),
                    title="编译 PDF",
                    tool="compile_latex_to_pdf",
                    arguments={"topic": topic},
                    thought="编译 LaTeX 生成 PDF，并发布为可下载链接。",
                ),
                PlanStep(
                    id=sid("review_content"),
                    title="内容审查",
                    tool="review_content",
                    arguments={"topic": topic, "subject": subject},
                    thought="对结构、准确性与可读性做最后自检，避免明显错误与空泛表述。",
                ),
            ]
        )

        if use_questions:
            rationale = f"计划：拆分/审核（已完成）→逐点网搜→逐点题库→聚合→生成→组装→保存→审查（学科：{subject}，难度：{difficulty}）"
        else:
            rationale = f"计划：拆分/审核（已完成）→逐点网搜→聚合→生成→组装→保存→审查（学科：{subject}，难度：{difficulty}）"
        return ExecutionPlan(topic=topic, steps=steps, rationale=rationale)

    def _parse_llm_plan(
        self,
        obj: Dict[str, Any],
        *,
        topic: str,
        subject: str,
        difficulty: str,
        iteration: int,
        issues: Optional[List[str]],
        allowed_tools: Dict[str, str],
        flags: Optional[Dict[str, Any]] = None,
    ) -> Optional[ExecutionPlan]:
        steps_raw = obj.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            return None

        def sid(prefix: str) -> str:
            return f"{prefix}-{iteration}-{uuid.uuid4().hex[:8]}"

        steps: List[PlanStep] = []
        for idx, item in enumerate(steps_raw[:200]):
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool") or "").strip()
            # split/review knowledge points are executed before planning; skip them if the model includes.
            if tool in {"split_knowledge_points", "review_knowledge_points"}:
                continue
            if tool not in allowed_tools:
                continue
            title = str(item.get("title") or tool).strip() or tool
            arguments = item.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            thought = str(item.get("thought") or "").strip()
            parallel_group = str(item.get("parallel_group") or "").strip()
            foreach_kp = bool(item.get("foreach_knowledge_point") or False)
            # For study-materials, most tools should run per knowledge point to:
            # - surface progress in the SubAgent panel
            # - keep each tool call focused (less context, fewer failures)
            if (
                tool
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
                and "foreach_knowledge_point" not in item
            ):
                foreach_kp = True
            foreach_limit = 0
            try:
                foreach_limit = int(item.get("foreach_limit") or 0)
            except Exception:
                foreach_limit = 0
            step_id = str(item.get("id") or "").strip() or sid(f"{tool}-{idx}")

            steps.append(
                PlanStep(
                    id=step_id,
                    title=title,
                    tool=tool,
                    arguments=dict(arguments),
                    parallel_group=parallel_group,
                    thought=thought,
                    foreach_knowledge_point=foreach_kp,
                    foreach_limit=max(0, foreach_limit),
                )
            )

        if not steps:
            return None

        # Ensure essential finishing steps exist.
        required_tail = [
            "generate_study_material",
            "assemble_study_archive",
            "save_markdown_file",
            "export_study_markdown",
            "convert_markdown_to_latex",
            "refine_latex",
            "compile_latex_to_pdf",
            "review_content",
        ]
        existing_tools = {s.tool for s in steps}
        for tool in required_tail:
            if tool in existing_tools:
                continue
            if tool == "generate_study_material":
                preset = str(flags.get("preset") or "standard").strip().lower() or "standard"
                requirements = str(flags.get("requirements") or "").strip()
                enable_diagrams = bool(flags.get("enable_diagrams")) if "enable_diagrams" in flags else True
                enable_questions = bool(flags.get("enable_questions")) if "enable_questions" in flags else False
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="生成概念讲解（按知识点）",
                        tool=tool,
                        arguments={
                            "topic": topic,
                            "subject": subject,
                            "preset": preset,
                            "requirements": requirements,
                            "max_examples": 0,
                            "max_points": 1,
                            "max_web_results": 10,
                            "max_web_pages": 2,
                            "max_page_chars": 2600,
                            "with_questions": bool(enable_questions),
                            # Diagrams are generated in a separate tool stage (generate_diagrams).
                            "with_diagrams": False,
                        },
                        foreach_knowledge_point=True,
                        thought="为当前知识点生成概念讲解草稿（配图在后续阶段生成）。",
                    )
                )
            elif tool == "assemble_study_archive":
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="组装自学档案 Markdown",
                        tool=tool,
                        arguments={"topic": topic, "subject": subject},
                        thought="整理为 Markdown，自学结构更清晰。",
                    )
                )
            elif tool == "save_markdown_file":
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="保存 Markdown 到文件",
                        tool=tool,
                        arguments={"topic": topic, "dir": "study_archives"},
                        thought="保存到本地文件，方便后续复习。",
                    )
                )
            elif tool == "export_study_markdown":
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="导出 Markdown 下载文件",
                        tool=tool,
                        arguments={"topic": topic},
                        thought="发布 Markdown 为下载链接（不在页面渲染全文）。",
                    )
                )
            elif tool == "convert_markdown_to_latex":
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="Markdown → LaTeX（ElegantBook）",
                        tool=tool,
                        arguments={"topic": topic, "subject": subject},
                        thought="将 Markdown 转为 ElegantBook LaTeX，以便编译 PDF。",
                    )
                )
            elif tool == "refine_latex":
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="LaTeX 二次修订",
                        tool=tool,
                        arguments={"topic": topic, "subject": subject},
                        thought="对 LaTeX 做二次修订，减少排版/编译问题。",
                    )
                )
            elif tool == "compile_latex_to_pdf":
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="编译 PDF",
                        tool=tool,
                        arguments={"topic": topic},
                        thought="编译 LaTeX 得到 PDF 并发布下载链接。",
                    )
                )
            elif tool == "review_content":
                steps.append(
                    PlanStep(
                        id=sid(tool),
                        title="内容审查",
                        tool=tool,
                        arguments={"topic": topic, "subject": subject},
                        thought="最后审查结构与可靠性，避免明显错误。",
                    )
                )

        # Ensure the new multi-stage study-materials pipeline is visible and executed even when
        # the planner LLM omits some steps.
        preset = str(flags.get("preset") or "standard").strip().lower() or "standard"
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = "standard"
        requirements = str(flags.get("requirements") or "").strip()
        enable_diagrams = bool(flags.get("enable_diagrams")) if "enable_diagrams" in flags else True

        def _find_first(tool_name: str, *, start: int = 0, end: Optional[int] = None) -> int:
            hi = len(steps) if end is None else max(0, min(int(end), len(steps)))
            lo = max(0, min(int(start), len(steps)))
            for j in range(lo, hi):
                if steps[j].tool == tool_name:
                    return j
            return -1

        def _find_last_before(tool_name: str, before: int) -> int:
            for j in range(min(before - 1, len(steps) - 1), -1, -1):
                if steps[j].tool == tool_name:
                    return j
            return -1

        gen_idx = _find_first("generate_study_material")
        if gen_idx != -1:
            # Ensure aggregate exists before generation (writer expects aggregated items).
            agg_idx = _find_last_before("aggregate_knowledge", gen_idx)
            if agg_idx == -1:
                steps.insert(
                    gen_idx,
                    PlanStep(
                        id=sid("aggregate_knowledge"),
                        title="聚合多源资料（按知识点）",
                        tool="aggregate_knowledge",
                        arguments={"topic": topic, "subject": subject},
                        thought="把网搜/题库结果按知识点聚合，形成可用于写作的统一素材。",
                        foreach_knowledge_point=True,
                    ),
                )
                gen_idx += 1
                agg_idx = gen_idx - 1

            # Pre-write pipeline: synthesize_sources ∥ detect_knowledge_type → generate_outline
            between_tools = {s.tool for s in steps[agg_idx + 1 : gen_idx]}
            insert_pos = agg_idx + 1
            pre_steps: List[PlanStep] = []
            if "synthesize_sources" not in between_tools:
                pre_steps.append(
                    PlanStep(
                        id=sid("synthesize_sources"),
                        title="综合源简报（按知识点）",
                        tool="synthesize_sources",
                        arguments={"topic": topic, "subject": subject},
                        parallel_group="kp_prewrite",
                        thought="对聚合素材去噪并提炼关键事实，生成结构化源简报，降低写作噪声与上下文长度。",
                        foreach_knowledge_point=True,
                    )
                )
            if "detect_knowledge_type" not in between_tools:
                pre_steps.append(
                    PlanStep(
                        id=sid("detect_knowledge_type"),
                        title="检测知识类型（按知识点）",
                        tool="detect_knowledge_type",
                        arguments={"topic": topic, "subject": subject},
                        parallel_group="kp_prewrite",
                        thought="判断知识点类型（定义/定理/算法等），为自适应大纲与写作提供结构先验。",
                        foreach_knowledge_point=True,
                    )
                )
            if pre_steps:
                steps[insert_pos:insert_pos] = pre_steps
                gen_idx += len(pre_steps)

            between_tools = {s.tool for s in steps[agg_idx + 1 : gen_idx]}
            if "generate_outline" not in between_tools:
                steps.insert(
                    gen_idx,
                    PlanStep(
                        id=sid("generate_outline"),
                        title="生成自适应大纲（按知识点）",
                        tool="generate_outline",
                        arguments={"topic": topic, "subject": subject, "preset": preset, "requirements": requirements},
                        thought="基于知识类型与源简报生成写作大纲（含验证标准），为分段并行写作做准备。",
                        foreach_knowledge_point=True,
                    ),
                )
                gen_idx += 1

            # Ensure diagrams are generated in a dedicated stage (generate_diagrams).
            try:
                gen_args = dict(steps[gen_idx].arguments or {})
                gen_args.setdefault("topic", topic)
                gen_args.setdefault("subject", subject)
                gen_args.setdefault("preset", preset)
                gen_args.setdefault("requirements", requirements)
                gen_args["with_diagrams"] = False
                steps[gen_idx].arguments = gen_args
            except Exception:
                pass

            # Post-write pipeline: critique_draft ∥ generate_diagrams → refine_draft
            assemble_idx = _find_first("assemble_study_archive", start=gen_idx + 1)
            post_end = assemble_idx if assemble_idx != -1 else len(steps)
            critique_idx = _find_first("critique_draft", start=gen_idx + 1, end=post_end)
            diagrams_idx = _find_first("generate_diagrams", start=gen_idx + 1, end=post_end) if enable_diagrams else -1
            refine_idx = _find_first("refine_draft", start=gen_idx + 1, end=post_end)

            if enable_diagrams:
                if critique_idx == -1 and diagrams_idx == -1:
                    steps.insert(
                        gen_idx + 1,
                        PlanStep(
                            id=sid("critique_draft"),
                            title="自我批判（按知识点）",
                            tool="critique_draft",
                            arguments={"topic": topic, "subject": subject},
                            parallel_group="kp_postwrite",
                            thought="对草稿多维度审查并给出可执行修订指令。",
                            foreach_knowledge_point=True,
                        ),
                    )
                    steps.insert(
                        gen_idx + 2,
                        PlanStep(
                            id=sid("generate_diagrams"),
                            title="生成教学配图（按知识点）",
                            tool="generate_diagrams",
                            arguments={"topic": topic, "subject": subject, "preset": preset},
                            parallel_group="kp_postwrite",
                            thought="为知识点生成必要的示意图（与自我批判并行）。",
                            foreach_knowledge_point=True,
                        ),
                    )
                    critique_idx = gen_idx + 1
                    diagrams_idx = gen_idx + 2
                    post_end += 2
                elif critique_idx != -1 and diagrams_idx == -1:
                    try:
                        steps[critique_idx].parallel_group = "kp_postwrite"
                    except Exception:
                        pass
                    steps.insert(
                        critique_idx + 1,
                        PlanStep(
                            id=sid("generate_diagrams"),
                            title="生成教学配图（按知识点）",
                            tool="generate_diagrams",
                            arguments={"topic": topic, "subject": subject, "preset": preset},
                            parallel_group="kp_postwrite",
                            thought="为知识点生成必要的示意图（与自我批判并行）。",
                            foreach_knowledge_point=True,
                        ),
                    )
                    diagrams_idx = critique_idx + 1
                    post_end += 1
                elif critique_idx == -1 and diagrams_idx != -1:
                    try:
                        steps[diagrams_idx].parallel_group = "kp_postwrite"
                    except Exception:
                        pass
                    steps.insert(
                        diagrams_idx,
                        PlanStep(
                            id=sid("critique_draft"),
                            title="自我批判（按知识点）",
                            tool="critique_draft",
                            arguments={"topic": topic, "subject": subject},
                            parallel_group="kp_postwrite",
                            thought="对草稿多维度审查并给出可执行修订指令。",
                            foreach_knowledge_point=True,
                        ),
                    )
                    critique_idx = diagrams_idx
                    diagrams_idx += 1
                    post_end += 1
                else:
                    # Both exist: at least mark them as a parallel group; they only run concurrently
                    # when they are contiguous (we avoid reordering user-authored plans).
                    try:
                        steps[critique_idx].parallel_group = steps[critique_idx].parallel_group or "kp_postwrite"
                    except Exception:
                        pass
                    try:
                        steps[diagrams_idx].parallel_group = steps[diagrams_idx].parallel_group or "kp_postwrite"
                    except Exception:
                        pass
            else:
                if critique_idx == -1:
                    steps.insert(
                        gen_idx + 1,
                        PlanStep(
                            id=sid("critique_draft"),
                            title="自我批判（按知识点）",
                            tool="critique_draft",
                            arguments={"topic": topic, "subject": subject},
                            thought="对草稿多维度审查并给出可执行修订指令。",
                            foreach_knowledge_point=True,
                        ),
                    )
                    critique_idx = gen_idx + 1
                    post_end += 1

            if refine_idx == -1:
                insert_after = max([x for x in [critique_idx, diagrams_idx] if x != -1] or [gen_idx])
                steps.insert(
                    insert_after + 1,
                    PlanStep(
                        id=sid("refine_draft"),
                        title="精炼修订（按知识点）",
                        tool="refine_draft",
                        arguments={"topic": topic, "subject": subject},
                        thought="根据批判意见对草稿做定向修订（高分则跳过）。",
                        foreach_knowledge_point=True,
                    ),
                )

        rationale = str(obj.get("rationale") or "").strip()
        if not rationale:
            rationale = f"计划：自主规划（学科：{subject}，难度：{difficulty}）"

        # If reflection issues exist, allow the model to add revise step; otherwise we keep it optional.
        if iteration > 0 and issues and "revise_markdown" not in existing_tools:
            steps.append(
                PlanStep(
                    id=sid("revise_markdown"),
                    title="根据审查问题修订 Markdown",
                    tool="revise_markdown",
                    arguments={"issues": issues},
                    thought="按审查问题修订内容。",
                )
            )

        return ExecutionPlan(topic=topic, steps=steps, rationale=rationale)

    async def plan(
        self,
        *,
        topic: str,
        user_profile: UserProfile,
        context: CompressedContext,
        iteration: int = 0,
    ) -> ExecutionPlan:
        topic = (topic or "").strip()
        subject = str(user_profile.preferences.get("subject") or DEFAULT_SUBJECT).strip() or DEFAULT_SUBJECT
        difficulty = _difficulty_from_profile(user_profile)
        flags = _study_flags(context)
        allowed_tools = _build_allowed_tools(
            enable_questions=bool(flags.get("enable_questions")),
            enable_extra_tools=bool(flags.get("enable_extra_tools")),
            enable_diagrams=bool(flags.get("enable_diagrams")),
        )

        last_reflection = context.working_memory.get("last_reflection") or {}
        issues = last_reflection.get("issues") if isinstance(last_reflection, dict) else None

        # If planner LLM isn't configured, use a deterministic fallback plan.
        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            return self._fallback_plan(
                topic=topic,
                subject=subject,
                difficulty=difficulty,
                iteration=iteration,
                issues=issues if isinstance(issues, list) else None,
                flags=flags,
            )

        tool_desc = "\n".join([f"- {k}: {v}" for k, v in allowed_tools.items()])
        notes: List[str] = [
            "必须输出 JSON 对象，不要 Markdown，不要额外解释文字。",
            "知识点已在 Plan 阶段前置拆分并审核，计划不需要包含 split_knowledge_points/review_knowledge_points。",
            "建议对 web_search_knowledge / aggregate_knowledge / generate_study_material 使用 foreach_knowledge_point=true，便于前端显示逐知识点进度。",
            "当你使用 foreach_knowledge_point=true 时，请尽量把这些步骤连续排列（执行器会按知识点 DFS 深挖：一个知识点做完完整研究链再换下一个）。",
            "并行建议：可用 parallel_group 标记「互不依赖的连续步骤」并行执行；例如：aggregate_knowledge 后并行 synthesize_sources ∥ detect_knowledge_type；写作后并行 critique_draft ∥ generate_diagrams。",
            "每一步请给出 thought（1-2 句，解释做这一步的目的；避免冗长推理）。",
            "steps 数量允许更长：每个知识点可 6~20 个工具调用；总 steps 可到 200（必要时）。",
            "计划允许可变长度 steps：你可以根据 reflection_issues/来源覆盖情况决定追加检索、跳过不必要步骤，或只对不足的知识点做修订（系统可能会在解析阶段补齐必要的收尾步骤）。",
        ]
        if bool(flags.get("enable_diagrams")):
            notes.extend(
                [
                    "你可以自主决定是否画图，并自行调度绘图工具多次（总计建议 3~12 次，按需要可更多/更少）。",
                    "推荐：优先调用 generate_diagrams（高层工具，会自动规划并调用 tikz_to_svg/seedream_generate）。",
                    "绘图工具支持 foreach_knowledge_point=true（推荐用于逐知识点配图）。每次绘图应传入 knowledge_point 或使用 foreach_knowledge_point 让执行器自动注入 knowledge_points=[kp]。",
                    "tikz_to_svg 参数示例：{\"knowledge_point\":\"...\",\"alt\":\"...\",\"caption\":\"...\",\"tikz\":\"\\\\begin{tikzpicture}...\\\\end{tikzpicture}\",\"preamble\":\"\\\\usetikzlibrary{arrows.meta,calc}\"}",
                    "seedream_generate 参数示例：{\"knowledge_point\":\"...\",\"alt\":\"...\",\"caption\":\"...\",\"prompt\":\"一张用于教学的简洁插图：...\",\"size\":\"1024x1024\",\"n\":1}",
                    "说明：绘图工具会把图片结果累积保存，assemble_study_archive 会自动插入到对应知识点。",
                ]
            )
        preset = str(flags.get("preset") or "standard")
        if preset == "quick":
            notes.append("当前 preset=quick：优先保证速度与结构清晰，尽量减少额外检索工具与轮次。")
        elif preset == "deep":
            notes.append("当前 preset=deep：允许更多检索与更深入讲解；来源不足时可追加检索轮次。")
            notes.append("建议：对每个知识点至少做 2 轮 web_search_knowledge（第一轮概念/直观，第二轮条件/反例/推导）。")
        elif preset == "research":
            notes.append("当前 preset=research：研究型输出（多轮检索 + 更严格的条件/反例/推导覆盖），可能更慢。")
            notes.append("建议：对每个知识点做 2~3 轮 web_search_knowledge（概念/直观 → 条件/反例/推导 → 应用/典型问题），不足再追加。")

        requirements = str(flags.get("requirements") or "").strip()
        if requirements:
            notes.append(f"额外要求（写作风格/约束）：{requirements[:220]}")

        if "browse_web_pages" in allowed_tools:
            notes.extend(
                [
                    "DeepResearch建议：优先做 1~2 轮 web_search_knowledge（include_summary=true；query_hint 覆盖：定义/性质/证明/应用/误区），必要时再追加轮次或调用 browse_web_pages 提取网页正文摘录。",
                    "可选来源：对关键知识点可补充 stackexchange_search（问答解释/易错）、github_search（笔记/教程仓库）、mediawiki_search（Wikibooks/ProofWiki 等）。",
                ]
            )
        else:
            notes.append(
                "DeepResearch建议：优先做 1~2 轮 web_search_knowledge（include_summary=true；query_hint 覆盖：定义/性质/证明/应用/误区）；来源不足时再追加轮次。"
            )
        prompt = {
            "task": topic,
            "subject": subject,
            "difficulty": difficulty,
            "ability_score": float(user_profile.ability_score or 0.5),
            "iteration": iteration,
            "reflection_issues": issues if isinstance(issues, list) else [],
            "allowed_tools": list(allowed_tools.keys()),
            "study_flags": flags,
            "notes": notes,
            "tool_descriptions": tool_desc,
        }

        system = (
            "你是自学资料生成系统的 Planner。你要输出一个可执行的计划 JSON。\n"
            "输出 schema:\n"
            '{\n  "rationale": "string",\n  "steps": [\n'
            '    {"id": "optional", "title": "string", "tool": "string", "arguments": {}, '
            '"parallel_group": "string", "thought": "string", "foreach_knowledge_point": false, "foreach_limit": 0}\n'
            "  ]\n}\n"
            "严格要求：只输出 JSON。"
        )

        try:
            text = await self._call_planner_llm(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                max_tokens=2000,
            )
            obj = _extract_json_obj(text)
            parsed = self._parse_llm_plan(
                obj,
                topic=topic,
                subject=subject,
                difficulty=difficulty,
                iteration=iteration,
                issues=issues if isinstance(issues, list) else None,
                allowed_tools=allowed_tools,
                flags=flags,
            )
            if parsed is not None:
                return parsed
        except Exception:
            pass

        return self._fallback_plan(
            topic=topic,
            subject=subject,
            difficulty=difficulty,
            iteration=iteration,
            issues=issues if isinstance(issues, list) else None,
            flags=flags,
        )
