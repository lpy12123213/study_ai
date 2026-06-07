"""Execution plan builder for the study-materials agent.

The public entrypoint remains `backend.agent.planner.Planner`, but the
implementation now lives under `backend.agent.planning` to keep files smaller
and responsibilities clearer.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict, List, Optional

from backend.agent.config import AgentConfig
from backend.agent.mcp.registry import MCPToolRegistry
from backend.agent.planning.json_utils import _extract_json_obj
from backend.agent.planning.study_options import _difficulty_from_profile, _env_truthy, _study_flags
from backend.agent.planning.tool_catalog import build_allowed_tools
from backend.agent.types import CompressedContext, ExecutionPlan, PlanStep, UserProfile
from backend.core.logging_utils import get_logger
from backend.core.settings import (
    DEFAULT_SUBJECT,
    LESSON_PLAN_MAX_TOKENS,
    LESSON_PLAN_TEMPERATURE,
)
from backend.llm.client import chat_completion_text, is_llm_configured
from backend.llm.prompts import create_default_prompt_registry

logger = get_logger(__name__)


def _execution_plan_system_prompt() -> str:
    return create_default_prompt_registry().render("agent.planner.execution_plan.v1").content


class Planner:
    def __init__(self, *, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_env()

    async def _call_planner_llm(
        self, *, messages: List[Dict[str, str]], max_tokens: int = 6000
    ) -> tuple[str, str]:
        normalized_model = str(self.config.planner_model or "").strip()
        if not normalized_model:
            return "", "missing_model"

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
        except (TypeError, ValueError):
            timeout_s = 30.0
        timeout_s = max(10.0, min(timeout_s, 300.0))

        try:
            text = await asyncio.wait_for(
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
            return str(text or ""), ""
        except asyncio.TimeoutError:
            logger.warning("planner_llm_timeout; fallback", extra={"timeout_s": timeout_s, "model": normalized_model})
            return "", "timeout"
        except Exception as exc:
            logger.warning(
                "planner_llm_failed; fallback",
                extra={"error": str(exc), "model": normalized_model},
                exc_info=True,
            )
            return "", "error"

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

        use_questions = (
            bool(flags.get("enable_questions"))
            if "enable_questions" in flags
            else _env_truthy("STUDY_MATERIALS_ENABLE_QUESTIONS")
        )
        enable_extra_tools = (
            bool(flags.get("enable_extra_tools"))
            if "enable_extra_tools" in flags
            else _env_truthy("STUDY_MATERIALS_ENABLE_EXTRA_TOOLS")
        )
        enable_diagrams = bool(flags.get("enable_diagrams")) if "enable_diagrams" in flags else True
        requirements = str(flags.get("requirements") or "").strip()
        max_points_override = 0
        try:
            max_points_override = int(flags.get("max_points") or 0)
        except (TypeError, ValueError):
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

        # Performance: for quick/standard presets, run independent retrieval steps in parallel within each
        # knowledge point to reduce end-to-end latency. Deep/research presets already do multi-pass retrieval
        # and are more likely to hit rate limits, so keep them more conservative by default.
        retrieve_pg = "kp_retrieve" if preset in {"quick", "standard"} else ""
        extra_sources_pg = retrieve_pg if retrieve_pg else "kp_sources"

        steps: List[PlanStep] = [
            PlanStep(
                id=sid("web_search_knowledge"),
                title="联网搜索知识点（网址结果）",
                tool="web_search_knowledge",
                arguments={
                    "topic": topic,
                    "subject": subject,
                    "limit": web_limit,
                    "text_max_length": 6000,
                    "query_hint": "定义 概念 直观理解 性质 定理 证明 误区 应用",
                    "scope": "webpage",
                    "include_summary": False,
                    "concurrency": 3,
                    # SubAgent behavior: decompose the knowledge point into smaller questions before asking.
                    "decompose": True,
                    # SubAgent behavior: decompose -> ask. This improves quality and reduces "one big ask".
                    "sub_questions": sub_q_pass1,
                    "preset": preset,
                },
                foreach_knowledge_point=True,
                parallel_group=retrieve_pg,
                thought="为每个知识点检索可用讲解资料，优先返回可点击的搜索结果链接（概念为主）。",
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
                        "include_summary": False,
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
                        "include_summary": False,
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
                        arguments={
                            "topic": topic,
                            "subject": subject,
                            "lang": "zh",
                            "sentences": 4,
                            "max_content_length": 2500,
                        },
                        foreach_knowledge_point=True,
                        parallel_group=extra_sources_pg,
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
                        parallel_group=extra_sources_pg,
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
                        parallel_group=extra_sources_pg,
                        thought="补充高质量问答解释与易错点，提升可理解性。",
                    ),
                    PlanStep(
                        id=sid("github_search"),
                        title="代码/笔记检索（GitHub）",
                        tool="github_search",
                        arguments={"topic": topic, "subject": subject, "limit": 5, "include_readme": False},
                        foreach_knowledge_point=True,
                        parallel_group=extra_sources_pg,
                        thought="查找教程/笔记仓库，获取更接近“教学表达”的材料线索。",
                    ),
                    PlanStep(
                        id=sid("browse_web_pages"),
                        title="提取网页正文（节选）",
                        tool="browse_web_pages",
                        arguments={
                            "topic": topic,
                            "subject": subject,
                            "top_k": 2 if preset != "quick" else 1,
                            "max_chars": 12000,
                        },
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
                    parallel_group=extra_sources_pg,
                    thought="（可选）为每个知识点搜集例题与练习题；默认关闭以优先保证概念质量。",
                )
            )

        def _add_default(tool_name: str) -> None:
            spec = self._default_step_spec(
                tool_name,
                topic=topic,
                subject=subject,
                difficulty=difficulty,
                preset=preset,
                requirements=requirements,
                max_web_pages=max_web_pages,
                enable_diagrams=enable_diagrams,
                enable_questions=use_questions,
                issues=issues,
            )
            if not spec:
                return
            steps.append(
                PlanStep(
                    id=sid(tool_name),
                    title=str(spec.get("title") or tool_name),
                    tool=tool_name,
                    arguments=dict(spec.get("arguments") or {}),
                    foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                    parallel_group=str(spec.get("parallel_group") or ""),
                    thought=str(spec.get("thought") or ""),
                )
            )

        for tool_name in (
            "aggregate_knowledge",
            "synthesize_sources",
            "detect_knowledge_type",
            "generate_outline",
            "generate_study_material",
            "critique_draft",
            "generate_diagrams",
            "refine_draft",
            "assemble_study_archive",
        ):
            _add_default(tool_name)

        if iteration > 0 and issues:
            _add_default("revise_markdown")

        for tool_name in (
            "save_markdown_file",
            "export_study_markdown",
            "convert_markdown_to_latex",
            "refine_latex",
            "compile_latex_to_pdf",
            "review_content",
        ):
            _add_default(tool_name)

        if use_questions:
            rationale = f"计划：拆分/审核（已完成）→逐点网搜→逐点题库→聚合→生成→组装→保存→审查（学科：{subject}，难度：{difficulty}）"
        else:
            rationale = (
                f"计划：拆分/审核（已完成）→逐点网搜→聚合→生成→组装→保存→审查（学科：{subject}，难度：{difficulty}）"
            )
        return ExecutionPlan(topic=topic, steps=steps, rationale=rationale)

    def _default_step_spec(
        self,
        tool: str,
        *,
        topic: str,
        subject: str,
        difficulty: str,
        preset: str,
        requirements: str,
        max_web_pages: int,
        enable_diagrams: bool,
        enable_questions: bool,
        issues: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Single source of truth for common step defaults.

        Delegates to :func:`backend.agent.planning.step_specs.default_step_spec`
        so the same mapping is used by both ``_fallback_plan`` and
        ``_parse_llm_plan`` without drifting.
        """

        from backend.agent.planning.step_specs import default_step_spec

        return default_step_spec(
            tool,
            topic=topic,
            subject=subject,
            difficulty=difficulty,
            preset=preset,
            requirements=requirements,
            max_web_pages=max_web_pages,
            enable_diagrams=enable_diagrams,
            enable_questions=enable_questions,
            issues=issues,
        )

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
            except (TypeError, ValueError):
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

        flags = flags if isinstance(flags, dict) else {}
        preset = str(flags.get("preset") or "standard").strip().lower() or "standard"
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = "standard"
        requirements = str(flags.get("requirements") or "").strip()
        enable_diagrams = bool(flags.get("enable_diagrams")) if "enable_diagrams" in flags else True
        enable_questions = bool(flags.get("enable_questions")) if "enable_questions" in flags else False
        max_web_pages = 2
        if preset == "quick":
            max_web_pages = 1
        elif preset == "deep":
            max_web_pages = 3
        elif preset == "research":
            max_web_pages = 4

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
            spec = self._default_step_spec(
                tool,
                topic=topic,
                subject=subject,
                difficulty=difficulty,
                preset=preset,
                requirements=requirements,
                max_web_pages=max_web_pages,
                enable_diagrams=enable_diagrams,
                enable_questions=enable_questions,
                issues=issues,
            )
            if not spec:
                continue
            steps.append(
                PlanStep(
                    id=sid(tool),
                    title=str(spec.get("title") or tool),
                    tool=tool,
                    arguments=dict(spec.get("arguments") or {}),
                    foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                    parallel_group=str(spec.get("parallel_group") or ""),
                    thought=str(spec.get("thought") or ""),
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
                spec = self._default_step_spec(
                    "aggregate_knowledge",
                    topic=topic,
                    subject=subject,
                    difficulty=difficulty,
                    preset=preset,
                    requirements=requirements,
                    max_web_pages=max_web_pages,
                    enable_diagrams=enable_diagrams,
                    enable_questions=enable_questions,
                    issues=issues,
                )
                if spec:
                    steps.insert(
                        gen_idx,
                        PlanStep(
                            id=sid("aggregate_knowledge"),
                            title=str(spec.get("title") or "aggregate_knowledge"),
                            tool="aggregate_knowledge",
                            arguments=dict(spec.get("arguments") or {}),
                            foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                            parallel_group=str(spec.get("parallel_group") or ""),
                            thought=str(spec.get("thought") or ""),
                        ),
                    )
                gen_idx += 1
                agg_idx = gen_idx - 1

            # Pre-write pipeline: synthesize_sources ∥ detect_knowledge_type → generate_outline
            between_tools = {s.tool for s in steps[agg_idx + 1 : gen_idx]}
            insert_pos = agg_idx + 1
            pre_steps: List[PlanStep] = []
            if "synthesize_sources" not in between_tools:
                spec = self._default_step_spec(
                    "synthesize_sources",
                    topic=topic,
                    subject=subject,
                    difficulty=difficulty,
                    preset=preset,
                    requirements=requirements,
                    max_web_pages=max_web_pages,
                    enable_diagrams=enable_diagrams,
                    enable_questions=enable_questions,
                    issues=issues,
                )
                if spec:
                    pre_steps.append(
                        PlanStep(
                            id=sid("synthesize_sources"),
                            title=str(spec.get("title") or "synthesize_sources"),
                            tool="synthesize_sources",
                            arguments=dict(spec.get("arguments") or {}),
                            foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                            parallel_group=str(spec.get("parallel_group") or ""),
                            thought=str(spec.get("thought") or ""),
                        )
                    )
            if "detect_knowledge_type" not in between_tools:
                spec = self._default_step_spec(
                    "detect_knowledge_type",
                    topic=topic,
                    subject=subject,
                    difficulty=difficulty,
                    preset=preset,
                    requirements=requirements,
                    max_web_pages=max_web_pages,
                    enable_diagrams=enable_diagrams,
                    enable_questions=enable_questions,
                    issues=issues,
                )
                if spec:
                    pre_steps.append(
                        PlanStep(
                            id=sid("detect_knowledge_type"),
                            title=str(spec.get("title") or "detect_knowledge_type"),
                            tool="detect_knowledge_type",
                            arguments=dict(spec.get("arguments") or {}),
                            foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                            parallel_group=str(spec.get("parallel_group") or ""),
                            thought=str(spec.get("thought") or ""),
                        )
                    )
            if pre_steps:
                steps[insert_pos:insert_pos] = pre_steps
                gen_idx += len(pre_steps)

            between_tools = {s.tool for s in steps[agg_idx + 1 : gen_idx]}
            if "generate_outline" not in between_tools:
                spec = self._default_step_spec(
                    "generate_outline",
                    topic=topic,
                    subject=subject,
                    difficulty=difficulty,
                    preset=preset,
                    requirements=requirements,
                    max_web_pages=max_web_pages,
                    enable_diagrams=enable_diagrams,
                    enable_questions=enable_questions,
                    issues=issues,
                )
                if spec:
                    steps.insert(
                        gen_idx,
                        PlanStep(
                            id=sid("generate_outline"),
                            title=str(spec.get("title") or "generate_outline"),
                            tool="generate_outline",
                            arguments=dict(spec.get("arguments") or {}),
                            foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                            parallel_group=str(spec.get("parallel_group") or ""),
                            thought=str(spec.get("thought") or ""),
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
                logger.warning("planner_adjust_generate_step_args_failed", exc_info=True)

            # Post-write pipeline: critique_draft ∥ generate_diagrams → refine_draft
            assemble_idx = _find_first("assemble_study_archive", start=gen_idx + 1)
            post_end = assemble_idx if assemble_idx != -1 else len(steps)
            critique_idx = _find_first("critique_draft", start=gen_idx + 1, end=post_end)
            diagrams_idx = _find_first("generate_diagrams", start=gen_idx + 1, end=post_end) if enable_diagrams else -1
            refine_idx = _find_first("refine_draft", start=gen_idx + 1, end=post_end)

            if enable_diagrams:
                if critique_idx == -1 and diagrams_idx == -1:
                    spec = self._default_step_spec(
                        "critique_draft",
                        topic=topic,
                        subject=subject,
                        difficulty=difficulty,
                        preset=preset,
                        requirements=requirements,
                        max_web_pages=max_web_pages,
                        enable_diagrams=enable_diagrams,
                        enable_questions=enable_questions,
                        issues=issues,
                    )
                    if spec:
                        steps.insert(
                            gen_idx + 1,
                            PlanStep(
                                id=sid("critique_draft"),
                                title=str(spec.get("title") or "critique_draft"),
                                tool="critique_draft",
                                arguments=dict(spec.get("arguments") or {}),
                                foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                                parallel_group=str(spec.get("parallel_group") or ""),
                                thought=str(spec.get("thought") or ""),
                            ),
                        )

                    spec = self._default_step_spec(
                        "generate_diagrams",
                        topic=topic,
                        subject=subject,
                        difficulty=difficulty,
                        preset=preset,
                        requirements=requirements,
                        max_web_pages=max_web_pages,
                        enable_diagrams=enable_diagrams,
                        enable_questions=enable_questions,
                        issues=issues,
                    )
                    if spec:
                        steps.insert(
                            gen_idx + 2,
                            PlanStep(
                                id=sid("generate_diagrams"),
                                title=str(spec.get("title") or "generate_diagrams"),
                                tool="generate_diagrams",
                                arguments=dict(spec.get("arguments") or {}),
                                foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                                parallel_group=str(spec.get("parallel_group") or ""),
                                thought=str(spec.get("thought") or ""),
                            ),
                        )
                    critique_idx = gen_idx + 1
                    diagrams_idx = gen_idx + 2
                    post_end += 2
                elif critique_idx != -1 and diagrams_idx == -1:
                    try:
                        steps[critique_idx].parallel_group = "kp_postwrite"
                    except Exception:
                        logger.warning("planner_set_parallel_group_failed", exc_info=True)
                    spec = self._default_step_spec(
                        "generate_diagrams",
                        topic=topic,
                        subject=subject,
                        difficulty=difficulty,
                        preset=preset,
                        requirements=requirements,
                        max_web_pages=max_web_pages,
                        enable_diagrams=enable_diagrams,
                        enable_questions=enable_questions,
                        issues=issues,
                    )
                    if spec:
                        steps.insert(
                            critique_idx + 1,
                            PlanStep(
                                id=sid("generate_diagrams"),
                                title=str(spec.get("title") or "generate_diagrams"),
                                tool="generate_diagrams",
                                arguments=dict(spec.get("arguments") or {}),
                                foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                                parallel_group=str(spec.get("parallel_group") or ""),
                                thought=str(spec.get("thought") or ""),
                            ),
                        )
                    diagrams_idx = critique_idx + 1
                    post_end += 1
                elif critique_idx == -1 and diagrams_idx != -1:
                    try:
                        steps[diagrams_idx].parallel_group = "kp_postwrite"
                    except Exception:
                        logger.warning("planner_set_parallel_group_failed", exc_info=True)
                    spec = self._default_step_spec(
                        "critique_draft",
                        topic=topic,
                        subject=subject,
                        difficulty=difficulty,
                        preset=preset,
                        requirements=requirements,
                        max_web_pages=max_web_pages,
                        enable_diagrams=enable_diagrams,
                        enable_questions=enable_questions,
                        issues=issues,
                    )
                    if spec:
                        steps.insert(
                            diagrams_idx,
                            PlanStep(
                                id=sid("critique_draft"),
                                title=str(spec.get("title") or "critique_draft"),
                                tool="critique_draft",
                                arguments=dict(spec.get("arguments") or {}),
                                foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                                parallel_group=str(spec.get("parallel_group") or ""),
                                thought=str(spec.get("thought") or ""),
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
                        logger.warning("planner_set_parallel_group_failed", exc_info=True)
                    try:
                        steps[diagrams_idx].parallel_group = steps[diagrams_idx].parallel_group or "kp_postwrite"
                    except Exception:
                        logger.warning("planner_set_parallel_group_failed", exc_info=True)
            else:
                if critique_idx == -1:
                    spec = self._default_step_spec(
                        "critique_draft",
                        topic=topic,
                        subject=subject,
                        difficulty=difficulty,
                        preset=preset,
                        requirements=requirements,
                        max_web_pages=max_web_pages,
                        enable_diagrams=enable_diagrams,
                        enable_questions=enable_questions,
                        issues=issues,
                    )
                    if spec:
                        steps.insert(
                            gen_idx + 1,
                            PlanStep(
                                id=sid("critique_draft"),
                                title=str(spec.get("title") or "critique_draft"),
                                tool="critique_draft",
                                arguments=dict(spec.get("arguments") or {}),
                                foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                                parallel_group=str(spec.get("parallel_group") or ""),
                                thought=str(spec.get("thought") or ""),
                            ),
                        )
                    critique_idx = gen_idx + 1
                    post_end += 1

            if refine_idx == -1:
                insert_after = max([x for x in [critique_idx, diagrams_idx] if x != -1] or [gen_idx])
                spec = self._default_step_spec(
                    "refine_draft",
                    topic=topic,
                    subject=subject,
                    difficulty=difficulty,
                    preset=preset,
                    requirements=requirements,
                    max_web_pages=max_web_pages,
                    enable_diagrams=enable_diagrams,
                    enable_questions=enable_questions,
                    issues=issues,
                )
                if spec:
                    steps.insert(
                        insert_after + 1,
                        PlanStep(
                            id=sid("refine_draft"),
                            title=str(spec.get("title") or "refine_draft"),
                            tool="refine_draft",
                            arguments=dict(spec.get("arguments") or {}),
                            foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                            parallel_group=str(spec.get("parallel_group") or ""),
                            thought=str(spec.get("thought") or ""),
                        ),
                    )

        rationale = str(obj.get("rationale") or "").strip()
        if not rationale:
            rationale = f"计划：自主规划（学科：{subject}，难度：{difficulty}）"

        # If reflection issues exist, allow the model to add revise step; otherwise we keep it optional.
        if iteration > 0 and issues and "revise_markdown" not in existing_tools:
            spec = self._default_step_spec(
                "revise_markdown",
                topic=topic,
                subject=subject,
                difficulty=difficulty,
                preset=preset,
                requirements=requirements,
                max_web_pages=max_web_pages,
                enable_diagrams=enable_diagrams,
                enable_questions=enable_questions,
                issues=issues,
            )
            if spec:
                steps.append(
                    PlanStep(
                        id=sid("revise_markdown"),
                        title=str(spec.get("title") or "revise_markdown"),
                        tool="revise_markdown",
                        arguments=dict(spec.get("arguments") or {}),
                        foreach_knowledge_point=bool(spec.get("foreach_knowledge_point") or False),
                        parallel_group=str(spec.get("parallel_group") or ""),
                        thought=str(spec.get("thought") or ""),
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
        tool_registry: Optional[MCPToolRegistry] = None,
    ) -> tuple[ExecutionPlan, str]:
        topic = (topic or "").strip()
        subject = str(user_profile.preferences.get("subject") or DEFAULT_SUBJECT).strip() or DEFAULT_SUBJECT
        difficulty = _difficulty_from_profile(user_profile)
        flags = _study_flags(context)
        allowed_tools = build_allowed_tools(
            enable_questions=bool(flags.get("enable_questions")),
            enable_extra_tools=bool(flags.get("enable_extra_tools")),
            enable_diagrams=bool(flags.get("enable_diagrams")),
            tool_registry=tool_registry,
        )

        last_reflection = context.working_memory.get("last_reflection") or {}
        issues = last_reflection.get("issues") if isinstance(last_reflection, dict) else None

        # If planner LLM isn't configured, use a deterministic fallback plan.
        if not is_llm_configured():
            return (
                self._fallback_plan(
                    topic=topic,
                    subject=subject,
                    difficulty=difficulty,
                    iteration=iteration,
                    issues=issues if isinstance(issues, list) else None,
                    flags=flags,
                ),
                "llm_not_configured",
            )

        tool_desc = "\n".join([f"- {k}: {v}" for k, v in allowed_tools.items()])
        notes: List[str] = [
            "Output a JSON object only. Do not output Markdown or extra explanatory text.",
            "Knowledge points have already been split and reviewed before the Plan stage; the plan does not need split_knowledge_points or review_knowledge_points.",
            "Prefer foreach_knowledge_point=true for web_search_knowledge, aggregate_knowledge, and generate_study_material so the frontend can show per-knowledge-point progress.",
            "When using foreach_knowledge_point=true, keep these steps consecutive when practical. The executor performs DFS by knowledge point: complete one full research chain before moving to the next.",
            "Parallelism guidance: use parallel_group to mark consecutive independent steps for parallel execution, for example synthesize_sources parallel with detect_knowledge_type after aggregate_knowledge, or critique_draft parallel with generate_diagrams after writing.",
            "Each step must include thought in 1-2 sentences explaining the purpose of the step. Avoid verbose reasoning.",
            "A longer step list is allowed: each knowledge point may require 6-20 tool calls, and total steps may reach 200 when necessary.",
            "Variable-length plans are allowed: based on reflection_issues/source coverage, you may add retrieval, skip unnecessary steps, or revise only insufficient knowledge points. The system may add required finalization steps during parsing.",
        ]
        if bool(flags.get("enable_diagrams")):
            notes.extend(
                [
                    "You may independently decide whether diagrams are needed and schedule diagram tools multiple times. Recommended total: 3-12 calls, adjusted as needed.",
                    "Recommendation: prefer generate_diagrams, the high-level tool that plans and calls tikz_to_svg, asy_to_svg, or seedream_generate automatically.",
                    "Diagram tools support foreach_knowledge_point=true, recommended for per-knowledge-point diagrams. Each diagram call should pass knowledge_point or use foreach_knowledge_point so the executor injects knowledge_points=[kp].",
                    'tikz_to_svg 参数示例：{"knowledge_point":"...","alt":"...","caption":"...","tikz":"\\\\begin{tikzpicture}...\\\\end{tikzpicture}","preamble":"\\\\usetikzlibrary{arrows.meta,calc}"}',
                    'asy_to_svg 参数示例：{"knowledge_point":"...","alt":"...","caption":"...","asy":"size(120); draw((0,0)--(1,0)--(1,1)--cycle);"}',
                    'seedream_generate 参数示例：{"knowledge_point":"...","alt":"...","caption":"...","prompt":"一张用于教学的简洁插图：...","size":"1024x1024","n":1}',
                    "Note: diagram tools accumulate saved image results; assemble_study_archive automatically inserts them into the corresponding knowledge point.",
                ]
            )
        preset = str(flags.get("preset") or "standard")
        if preset == "quick":
            notes.append("Current preset=quick: prioritize speed and clear structure; minimize extra retrieval tools and rounds.")
        elif preset == "deep":
            notes.append("Current preset=deep: allow more retrieval and deeper explanations; add retrieval rounds when sources are insufficient.")
            notes.append(
                "Recommendation: run at least 2 web_search_knowledge rounds for each knowledge point: first for concepts/intuition, second for conditions/counterexamples/derivation."
            )
        elif preset == "research":
            notes.append("Current preset=research: research-oriented output with multi-round retrieval and stricter coverage of conditions, counterexamples, and derivation; may be slower.")
            notes.append(
                "Recommendation: run 2-3 web_search_knowledge rounds for each knowledge point: concepts/intuition -> conditions/counterexamples/derivation -> applications/typical questions; add more if insufficient."
            )

        requirements = str(flags.get("requirements") or "").strip()
        if requirements:
            notes.append(f"Extra requirements for writing style or constraints: {requirements[:220]}")

        if "browse_web_pages" in allowed_tools:
            notes.extend(
                [
                    "DeepResearch guidance: prefer 1-2 web_search_knowledge rounds first, default result-first, with query_hint covering definitions/properties/proofs/applications/misconceptions. Add rounds or call browse_web_pages for page excerpts only when needed.",
                    "Optional sources: for key knowledge points, add stackexchange_search for Q&A explanations/misconceptions, github_search for notes/tutorial repositories, and mediawiki_search for Wikibooks/ProofWiki, etc.",
                ]
            )
        else:
            notes.append(
                "DeepResearch guidance: prefer 1-2 web_search_knowledge rounds first, default result-first, with query_hint covering definitions/properties/proofs/applications/misconceptions. Add rounds only when sources are insufficient."
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

        system = _execution_plan_system_prompt()

        degraded_reason = ""
        try:
            text, degraded_reason = await self._call_planner_llm(
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
                return parsed, degraded_reason
        except Exception:
            logger.warning("planner_llm_plan_parse_failed; fallback", exc_info=True)

        return (
            self._fallback_plan(
                topic=topic,
                subject=subject,
                difficulty=difficulty,
                iteration=iteration,
                issues=issues if isinstance(issues, list) else None,
                flags=flags,
            ),
            degraded_reason or "parse_failed",
        )
