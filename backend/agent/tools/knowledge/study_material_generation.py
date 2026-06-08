from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from backend.agent.tools.utils.text_utils import _sanitize_explanation_markdown
from backend.agent.types import CompressedContext
from backend.core.settings import MAIN_MODEL, STUDY_MATERIALS_WRITER_MODEL
from backend.core.text_utils import clip_text as _clip_text
from backend.generation.question_library.curriculum_context import normalize_curriculum_context
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry

_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+.*?$", flags=re.M)
_KNOWLEDGE_TYPE_VALUES = {"definition", "theorem", "algorithm", "concept", "history", "experiment"}


def _registered_prompt(prompt_id: str) -> str:
    return create_default_prompt_registry().render(prompt_id).content


def _outline_system_prompt() -> str:
    return _registered_prompt("study.material.outline.v1")


def _section_writer_system_prompt() -> str:
    return _registered_prompt("study.material.section_writer.v1")


def _section_reviewer_system_prompt() -> str:
    return _registered_prompt("study.material.section_reviewer.v1")


def _section_revision_system_prompt() -> str:
    return _registered_prompt("study.material.section_revision.v1")


def _study_option_value(study_opts: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in study_opts:
            return study_opts.get(key)
    return None


def _grade_band_for_study(study_opts: Dict[str, Any]) -> str:
    raw = _study_option_value(study_opts, "grade_band", "gradeBand", "grade", "grade_id", "gradeId")
    return _clip_text(str(raw or "").strip(), 48) if str(raw or "").strip() else ""


def _curriculum_context_for_study(
    *,
    subject: str,
    knowledge_points: List[str],
    study_opts: Dict[str, Any],
) -> Dict[str, Any]:
    raw = _study_option_value(study_opts, "curriculum_context", "curriculumContext")
    ctx = normalize_curriculum_context(raw if isinstance(raw, dict) else {}, subject=subject)
    scope = dict(ctx.get("knowledge_scope") or {})
    in_scope = [str(x or "").strip() for x in (scope.get("in_scope") or []) if str(x or "").strip()]
    out_of_scope = [str(x or "").strip() for x in (scope.get("out_of_scope") or []) if str(x or "").strip()]
    seen = set(in_scope)
    for kp in knowledge_points or []:
        item = str(kp or "").strip()
        if item and item not in seen:
            seen.add(item)
            in_scope.append(item)
    ctx["knowledge_scope"] = {"in_scope": in_scope[:20], "out_of_scope": out_of_scope[:16]}
    return ctx


def _strip_markdown_headings(text: str) -> str:
    raw = str(text or "")
    if not raw.strip():
        return ""
    out = _MD_HEADING_RE.sub("", raw)
    out = "\n".join([ln.rstrip() for ln in out.splitlines() if ln.strip()])
    return out.strip()


def _summarize_markdown_for_context(md: str, *, limit: int = 220) -> str:
    text = _strip_markdown_headings(md)
    text = text.replace("```", "").strip()
    return _clip_text(text, limit)


def _collect_completed_overview(
    ctx: CompressedContext,
    *,
    current_kp: str,
    local_sections: List[Dict[str, Any]],
    limit: int = 8,
) -> List[Dict[str, str]]:
    """Build a compact list of already-covered knowledge points so the writer can avoid repetition."""

    current_kp = str(current_kp or "").strip()
    out: List[Dict[str, str]] = []
    seen: set[str] = set()

    def _add(kp: str, summary: str) -> None:
        k = str(kp or "").strip()
        s = str(summary or "").strip()
        if not k or k == current_kp:
            return
        if not s:
            return
        if k in seen:
            return
        seen.add(k)
        out.append({"knowledge_point": k, "title": k, "summary": _clip_text(s, 240)})

    # 1) Same tool-call earlier results (helps when generating multiple kps in one call).
    for sec in local_sections or []:
        if not isinstance(sec, dict):
            continue
        kp = str(sec.get("knowledge_point") or "").strip()
        md = str(sec.get("explanation_markdown") or "").strip()
        if kp and md:
            _add(kp, _summarize_markdown_for_context(md, limit=220))

    # 2) Previously generated material in working memory (helps across subagent runs).
    material = ctx.working_memory.get("generate_study_material")
    if isinstance(material, dict) and isinstance(material.get("sections"), list):
        for sec in material.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            kp = str(sec.get("knowledge_point") or "").strip()
            md = str(sec.get("explanation_markdown") or "").strip()
            if kp and md:
                _add(kp, _summarize_markdown_for_context(md, limit=220))

    # 3) Subagent summaries (best-effort; may exist even if full material wasn't generated).
    summaries = ctx.working_memory.get("subagent_summaries")
    if isinstance(summaries, dict):
        for kp, summary in list(summaries.items())[:20]:
            _add(str(kp or "").strip(), _clip_text(str(summary or "").strip(), 220))

    return out[: max(0, int(limit or 0))] if limit > 0 else out


def _extract_points(args: Dict[str, Any], ctx: CompressedContext) -> List[str]:
    provided = args.get("knowledge_points")
    if isinstance(provided, list):
        pts = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if pts:
            return pts[:15]

    split_res = ctx.working_memory.get("split_knowledge_points")
    if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
        pts = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()]
        if pts:
            return pts[:15]

    topic = str(args.get("topic") or ctx.current_task or "").strip()
    return [topic] if topic else []


def _heuristic_knowledge_type(kp: str) -> str:
    s = (kp or "").strip()
    if not s:
        return "concept"
    s_lower = s.lower()

    if any(x in s for x in ["实验", "探究", "测量", "装置", "仪器", "观测", "现象", "操作"]):
        return "experiment"
    if any(x in s for x in ["历史", "发展", "人物", "年代", "起源", "背景", "里程碑"]):
        return "history"

    # Prefer procedure/method wording before theorem keywords so "方程解法" is
    # treated as a solution method rather than a theorem-like statement.
    if any(
        x in s
        for x in [
            "算法",
            "排序",
            "搜索",
            "动态规划",
            "贪心",
            "回溯",
            "递归",
            "分治",
            "二分",
            "双指针",
            "滑动窗口",
            "解法",
            "方法",
            "技巧",
            "步骤",
            "流程",
            "推导",
            "证明思路",
            "分析",
            "分解",
        ]
    ) or any(x in s_lower for x in ["dp", "bfs", "dfs", "dijkstra"]):
        return "algorithm"

    if any(
        x in s for x in ["定理", "命题", "引理", "推论", "结论", "定律", "法则", "公式", "恒等式", "不等式", "方程"]
    ):
        return "theorem"

    if any(x in s for x in ["定义", "是什么", "含义", "概念", "记号", "符号", "术语"]):
        return "definition"
    return "concept"


def _default_outline_sections(knowledge_type: str, preset: str) -> List[Dict[str, Any]]:
    """A minimal outline fallback used when outline tool isn't called or LLM isn't configured.

    The goal is to keep the pipeline usable without forcing a rigid template across knowledge points.
    """

    kt = (knowledge_type or "").strip().lower()
    if kt not in _KNOWLEDGE_TYPE_VALUES:
        kt = "concept"

    deep = preset in {"deep", "research"}
    research = preset == "research"

    def sec(title: str, hints: List[str], verify: List[str]) -> Dict[str, Any]:
        return {"title": title, "hints": hints[:4], "verify": verify[:5]}

    if kt == "theorem":
        sections = [
            sec("结论与适用条件", ["一句话说明结论", "把适用条件写全"], ["条件明确", "结论明确"]),
            sec("直观理解与例子", ["用图像/类比解释直觉", "给一个最简单例子"], ["有直觉", "有例子"]),
            sec("边界情况/反例与易错点", ["哪些条件不可缺？缺了会怎样？", "给出典型反例或陷阱"], ["至少1个反例/陷阱（如适用）"]),
            sec("用法与题型思路", ["遇到题目时怎么用", "常用变形/等价表述（如适用）"], ["给出可执行步骤"]),
        ]
        if deep:
            sections.insert(
                3,
                sec(
                    "证明/推导思路（选读）",
                    ["给出推导/证明骨架（非细节）", "标注关键一步为什么这么做"],
                    ["有骨架（如适用）"],
                ),
            )
        if research:
            sections.append(sec("自检清单（选读）", ["列出3~6个自测问题"], ["有可操作自检项"]))
        return sections

    if kt == "algorithm":
        sections = [
            sec("目标与核心思路", ["这个方法解决什么问题", "一句话概括核心策略"], ["目标明确", "策略清晰"]),
            sec("步骤与复杂度", ["分步骤描述流程/伪代码", "时间/空间复杂度（如适用）"], ["步骤可执行", "复杂度明确（如适用）"]),
            sec("边界/易错点", ["边界条件", "常见实现坑"], ["至少2个易错点（如适用）"]),
            sec("例题/应用", ["给一个典型场景或题型", "说明如何落地使用"], ["有落地用法"]),
        ]
        if deep:
            sections.append(sec("正确性要点（选读）", ["关键不变式/贪心理由（如适用）"], ["有正确性理由（如适用）"]))
        return sections

    if kt == "experiment":
        return [
            sec("目的与原理", ["要验证/测量什么", "核心原理是什么"], ["目的明确", "原理清楚"]),
            sec("装置/变量与步骤", ["装置结构与变量控制", "操作步骤与现象观察"], ["步骤可复现"]),
            sec("数据处理与误差", ["如何计算/作图/拟合", "主要误差来源与减小方式"], ["至少2个误差来源（如适用）"]),
            sec("常见问题与改进", ["常见失败原因", "如何改进/排错"], ["有可执行建议"]),
        ]

    if kt == "history":
        return [
            sec("一句话概括与背景", ["先给出结论式摘要", "交代背景与动机"], ["有一句话概括"]),
            sec("发展脉络与关键节点", ["按时间/阶段梳理", "点出关键转折"], ["至少2~4个关键节点（如适用）"]),
            sec("影响与联系", ["它改变了什么", "与今天/相近概念的联系"], ["有影响总结"]),
        ]

    # concept / definition
    sections = [
        sec("动机与定义", ["它解决什么问题", "给出定义/核心表述"], ["定义清晰且自洽（如适用）"]),
        sec("直观理解与例子", ["用图像/类比解释", "给一个最简单例子"], ["有直觉+例子（如适用）"]),
        sec("关键性质/条件与易错点", ["列出关键性质/条件", "补充边界/反例/常见误区（如适用）"], ["性质/条件不自相矛盾"]),
        sec("应用/题型思路", ["如何使用/何时使用", "常见题型或场景"], ["有可执行步骤"]),
    ]
    if deep:
        sections.append(sec("推导/证明/方法骨架（选读）", ["给出推导/证明/方法的骨架（如适用）"], ["有骨架（如适用）"]))
    if research:
        sections.append(sec("自检清单（选读）", ["列出3~6个自测问题"], ["有可操作自检项"]))
    return sections


def _first_existing_diagram(ctx: CompressedContext, kp: str) -> Dict[str, Any]:
    blob = ctx.working_memory.get("diagrams")
    if not isinstance(blob, dict):
        return {}
    entries: List[Dict[str, Any]] = []
    if isinstance(blob.get("items"), list):
        entries = [x for x in (blob.get("items") or []) if isinstance(x, dict)]
    elif isinstance(blob.get("sections"), list):
        entries = [x for x in (blob.get("sections") or []) if isinstance(x, dict)]
    for it in entries:
        if str(it.get("knowledge_point") or "").strip() != kp:
            continue
        ds = it.get("diagrams")
        if isinstance(ds, list):
            first = next((d for d in ds if isinstance(d, dict)), None)
            return dict(first or {})
        return {}
    return {}


@dataclass
class _WriterAgentResult:
    markdown: str
    review: Dict[str, Any] = field(default_factory=dict)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    revisions: int = 0
    finish_reason: str = "stop"
    usage: Dict[str, Any] = field(default_factory=dict)
    continuations: int = 0
    source: str = "writer_agent"


class _KnowledgePointWriterAgent:
    """Small bounded writer loop for one knowledge point.

    The outer study-materials agent decides *when* to write; this inner agent decides
    whether the draft is good enough or needs one or more targeted revisions.
    """

    def __init__(
        self,
        *,
        knowledge_point: str,
        plan: Dict[str, Any],
        write_draft: Callable[[], Awaitable[Dict[str, Any]]],
        review_draft: Callable[[str], Awaitable[Dict[str, Any]]],
        revise_draft: Callable[[str, Dict[str, Any]], Awaitable[str]],
        max_revision_rounds: int = 1,
        emit_status: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        self.knowledge_point = str(knowledge_point or "").strip()
        self.plan = dict(plan or {})
        self.write_draft = write_draft
        self.review_draft = review_draft
        self.revise_draft = revise_draft
        self.max_revision_rounds = max(0, min(int(max_revision_rounds or 0), 5))
        self.emit_status = emit_status

    async def _emit(self, content: str) -> None:
        text = str(content or "").strip()
        if not text or self.emit_status is None:
            return
        try:
            await self.emit_status(text)
        except (RuntimeError, TypeError, ValueError):
            return

    @staticmethod
    def _normalize_review(review: Any) -> Dict[str, Any]:
        obj = dict(review or {}) if isinstance(review, dict) else {}
        issues_raw = obj.get("issues")
        suggestions_raw = obj.get("suggestions")
        issues = (
            [str(x or "").strip() for x in issues_raw if str(x or "").strip()]
            if isinstance(issues_raw, list)
            else []
        )
        suggestions = (
            [str(x or "").strip() for x in suggestions_raw if str(x or "").strip()]
            if isinstance(suggestions_raw, list)
            else []
        )
        passed = bool(obj.get("passed")) if "passed" in obj else not issues
        out = dict(obj)
        out["passed"] = passed
        out["issues"] = issues[:12]
        out["suggestions"] = suggestions[:12]
        return out

    async def run(self) -> _WriterAgentResult:
        actions: List[Dict[str, Any]] = [
            {
                "action": "plan",
                "knowledge_point": self.knowledge_point,
                "sections": len(self.plan.get("sections") or []) if isinstance(self.plan.get("sections"), list) else 0,
            }
        ]
        await self._emit(f"WriterAgent 启动：{self.knowledge_point}")

        draft = await self.write_draft()
        draft = dict(draft or {}) if isinstance(draft, dict) else {}
        markdown = str(draft.get("markdown") or "").strip()
        finish_reason = str(draft.get("finish_reason") or "stop").strip() or "stop"
        usage = draft.get("usage") if isinstance(draft.get("usage"), dict) else {}
        try:
            continuations = int(draft.get("continuations") or 0)
        except (TypeError, ValueError):
            continuations = 0
        source = str(draft.get("source") or "writer_agent").strip() or "writer_agent"
        actions.append({"action": "draft", "chars": len(markdown), "finish_reason": finish_reason})

        review = self._normalize_review(await self.review_draft(markdown))
        actions.append(
            {
                "action": "review",
                "passed": bool(review.get("passed")),
                "issues": list(review.get("issues") or [])[:6],
            }
        )

        revisions = 0
        while markdown and not bool(review.get("passed")) and revisions < self.max_revision_rounds:
            await self._emit(f"WriterAgent 修订：{self.knowledge_point}")
            revised = str(await self.revise_draft(markdown, review) or "").strip()
            if not revised:
                break
            markdown = revised
            revisions += 1
            actions.append(
                {
                    "action": "revise",
                    "round": revisions,
                    "issues": list(review.get("issues") or [])[:6],
                    "chars": len(markdown),
                }
            )

            review = self._normalize_review(await self.review_draft(markdown))
            actions.append(
                {
                    "action": "review",
                    "passed": bool(review.get("passed")),
                    "issues": list(review.get("issues") or [])[:6],
                }
            )

        await self._emit(f"WriterAgent 完成：{self.knowledge_point}")
        return _WriterAgentResult(
            markdown=markdown,
            review=review,
            actions=actions,
            revisions=revisions,
            finish_reason=finish_reason,
            usage=dict(usage),
            continuations=continuations,
            source=source,
        )


class StudyMaterialGenerationToolsMixin:
    async def _tool_generate_outline(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Generate an adaptive outline per knowledge point.

        Writes:
        - ctx.working_memory["outlines"][knowledge_point] = outline (dict)
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)

        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        preset = str(args.get("preset") or study_opts.get("preset") or "standard").strip().lower() or "standard"
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = "standard"
        requirements = str(args.get("requirements") or study_opts.get("requirements") or "").strip()
        if len(requirements) > 600:
            requirements = requirements[:599].rstrip() + "…"

        points = _extract_points(args, ctx)
        grade_band = _grade_band_for_study(study_opts)
        curriculum_context = _curriculum_context_for_study(
            subject=subject,
            knowledge_points=points,
            study_opts=study_opts,
        )

        source_briefs = ctx.working_memory.get("source_briefs")
        source_briefs = dict(source_briefs) if isinstance(source_briefs, dict) else {}

        source_facts = ctx.working_memory.get("source_facts")
        source_facts = dict(source_facts) if isinstance(source_facts, dict) else {}

        knowledge_types = ctx.working_memory.get("knowledge_types")
        knowledge_types = dict(knowledge_types) if isinstance(knowledge_types, dict) else {}

        model = str(
            os.getenv("STUDY_MATERIALS_OUTLINE_MODEL")
            or getattr(getattr(self, "config", None), "summarizer_model", "")
            or getattr(getattr(self, "config", None), "planner_model", "")
        ).strip()
        if not model:
            model = "gpt-4o-mini"

        def _sec_bounds() -> Tuple[int, int]:
            if preset == "quick":
                return (3, 6)
            if preset == "deep":
                return (4, 9)
            if preset == "research":
                return (5, 11)
            return (4, 8)

        sec_min, sec_max = _sec_bounds()

        async def _outline_one(kp: str) -> Dict[str, Any]:
            kt_obj = knowledge_types.get(kp) if isinstance(knowledge_types.get(kp), dict) else {}
            knowledge_type = str(kt_obj.get("knowledge_type") or "").strip().lower()
            if knowledge_type not in _KNOWLEDGE_TYPE_VALUES:
                knowledge_type = _heuristic_knowledge_type(kp)

            brief = source_briefs.get(kp) if isinstance(source_briefs.get(kp), dict) else {}
            facts_raw = source_facts.get(kp)
            facts_list = facts_raw if isinstance(facts_raw, list) else []
            facts: List[Dict[str, Any]] = []
            for f in facts_list[:16]:
                if not isinstance(f, dict):
                    continue
                fact = str(f.get("fact") or "").strip()
                if not fact:
                    continue
                try:
                    conf = float(f.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    conf = 0.0
                facts.append({"fact": _clip_text(fact, 180), "confidence": max(0.0, min(conf, 1.0))})

            if not is_llm_configured():
                if strict_llm:
                    raise RuntimeError("llm_not_configured")
                outline = {"sections": _default_outline_sections(knowledge_type, preset)}
                ctx.working_memory.setdefault("outlines", {})[kp] = outline
                return {
                    "knowledge_point": kp,
                    "outline": outline,
                    "source": "heuristic",
                    "knowledge_type": knowledge_type,
                }

            prompt = {
                "topic": topic,
                "subject": subject,
                "knowledge_point": kp,
                "preset": preset,
                "knowledge_type": knowledge_type,
                "grade_band": grade_band,
                "curriculum_context": curriculum_context,
                "ability_level": str(ctx.user_profile.ability_level or "unknown"),
                "ability_score": float(ctx.user_profile.ability_score or 0.5),
                "requirements": requirements,
                "source_brief": brief,
                "source_facts": facts,
                "constraints": [
                    "Design an explanation outline for this knowledge point for later section-by-section writing.",
                    f"sections 数量建议：{sec_min}~{sec_max} 个（不必凑满，但要覆盖核心内容）。",
                    'Output strict JSON: {"sections":[{"title":"...","hints":["..."],"verify":["..."]}, ...]}.',
                    "title must be a concise phrase in the user's/topic language. Avoid mechanically reusing fixed template titles; reflect the specific knowledge point.",
                    "hints 每节 1~4 条，短提示即可。",
                    "verify 为该节写完后的『验证标准』，每节 2~5 条，越可操作越好。",
                    "Try to cover definitions/statements, intuition, key conclusions or properties/conditions, common misconceptions, applications/solution framework, or summary. Merging/splitting is allowed; omit inapplicable items only when verify reflects the coverage intent or explains the omission/substitute.",
                    "Respect curriculum_context and grade_band: keep knowledge boundaries, prerequisites, and depth aligned with the stated school stage.",
                    "If source_facts are provided, include 1-2 verify checks that the section is consistent with key facts. Low-confidence facts must be framed as inferences.",
                    "Do not output examples/exercises, URLs, or Markdown.",
                ],
            }

            raw = await self._call_llm_text(
                messages=[
                    {"role": "system", "content": _outline_system_prompt()},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                model=model,
                temperature=0.2,
                max_tokens=1400,
                response_format={"type": "json_object"},
                raise_on_fail=strict_llm,
            )
            obj = self._extract_json_obj(raw)
            sections_raw = obj.get("sections") if isinstance(obj, dict) else None
            sections: List[Dict[str, Any]] = []
            if isinstance(sections_raw, list):
                for sec in sections_raw[: max(4, sec_max)]:
                    if not isinstance(sec, dict):
                        continue
                    title = str(sec.get("title") or "").strip().strip("# ").strip()
                    if not title:
                        continue
                    hints = sec.get("hints")
                    verify = sec.get("verify")
                    hints_list = [str(x).strip() for x in hints if str(x).strip()] if isinstance(hints, list) else []
                    verify_list = [str(x).strip() for x in verify if str(x).strip()] if isinstance(verify, list) else []
                    sections.append({"title": title[:48], "hints": hints_list[:6], "verify": verify_list[:8]})

            if not sections:
                sections = _default_outline_sections(knowledge_type, preset)

            outline = {"sections": sections}
            ctx.working_memory.setdefault("outlines", {})[kp] = outline
            return {"knowledge_point": kp, "outline": outline, "source": "llm", "knowledge_type": knowledge_type}

        items = [await _outline_one(kp) for kp in points]
        return {"topic": topic, "subject": subject, "preset": preset, "items": items}

    async def _tool_generate_study_material(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Write study material per knowledge point (section-level parallel writing)."""

        aggregated = ctx.working_memory.get("aggregate_knowledge") or ctx.working_memory.get("aggregated") or {}
        if not isinstance(aggregated, dict):
            aggregated = {}
        synthesized = ctx.working_memory.get("synthesize_sources") or {}
        if not isinstance(synthesized, dict):
            synthesized = {}

        topic = str(
            args.get("topic") or aggregated.get("topic") or synthesized.get("topic") or ctx.current_task
        ).strip()
        subject = str(
            args.get("subject")
            or aggregated.get("subject")
            or synthesized.get("subject")
            or ctx.user_profile.preferences.get("subject")
            or ""
        ).strip()
        items_in = aggregated.get("items") if isinstance(aggregated.get("items"), list) else []
        items_in = [x for x in items_in if isinstance(x, dict)]
        if not items_in:
            items_in = synthesized.get("items") if isinstance(synthesized.get("items"), list) else []
            items_in = [x for x in items_in if isinstance(x, dict)]

        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        strict_llm = self._strict_llm(ctx, args)
        preset = str(args.get("preset") or study_opts.get("preset") or "standard").strip().lower() or "standard"
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = "standard"
        requirements = str(args.get("requirements") or study_opts.get("requirements") or "").strip()
        if len(requirements) > 600:
            requirements = requirements[:599].rstrip() + "…"

        requested = args.get("knowledge_points")
        if isinstance(requested, list) and requested:
            wanted = {str(x or "").strip() for x in requested if str(x or "").strip()}
            items_in = [x for x in items_in if str(x.get("knowledge_point") or "").strip() in wanted]

        max_points = max(1, min(int(args.get("max_points") or 8), 15))
        max_web_results = max(3, min(int(args.get("max_web_results") or 8), 25))
        max_web_pages = max(0, min(int(args.get("max_web_pages") or 2), 8))
        max_page_chars = max(500, min(int(args.get("max_page_chars") or 3200), 8000))
        with_questions = bool(args.get("with_questions", False))
        selected_kps_for_context = [
            str(item.get("knowledge_point") or "").strip()
            for item in items_in[:max_points]
            if isinstance(item, dict) and str(item.get("knowledge_point") or "").strip()
        ]
        grade_band = _grade_band_for_study(study_opts)
        curriculum_context = _curriculum_context_for_study(
            subject=subject,
            knowledge_points=selected_kps_for_context,
            study_opts=study_opts,
        )

        section_conc_raw = args.get("section_concurrency") or os.getenv("STUDY_MATERIALS_SECTION_CONCURRENCY") or "3"
        try:
            section_concurrency = int(section_conc_raw)
        except (TypeError, ValueError):
            section_concurrency = 3
        section_concurrency = max(1, min(section_concurrency, 6))

        revision_rounds_raw = (
            args.get("writer_revision_rounds")
            or os.getenv("STUDY_MATERIALS_WRITER_AGENT_REVISION_ROUNDS")
            or "1"
        )
        try:
            writer_revision_rounds = int(revision_rounds_raw)
        except (TypeError, ValueError):
            writer_revision_rounds = 1
        writer_revision_rounds = max(0, min(writer_revision_rounds, 3))

        if strict_llm and not is_llm_configured():
            raise RuntimeError("llm_not_configured")

        writer_model = str(
            STUDY_MATERIALS_WRITER_MODEL
            or getattr(getattr(self, "config", None), "planner_model", "")
            or getattr(getattr(self, "config", None), "summarizer_model", "")
        ).strip()
        if not writer_model:
            # Writing is the highest-impact stage; default to the main model.
            writer_model = str(MAIN_MODEL or "").strip() or "gpt-4o-mini"

        # Per-section token cap (shorter prompts -> faster).
        if preset == "quick":
            section_max_tokens = 1800
            cont_limit = 1
        elif preset == "deep":
            section_max_tokens = 2600
            cont_limit = 2
        elif preset == "research":
            section_max_tokens = 3200
            cont_limit = 2
        else:
            section_max_tokens = 2200
            cont_limit = 1

        source_briefs = ctx.working_memory.get("source_briefs")
        source_briefs = dict(source_briefs) if isinstance(source_briefs, dict) else {}
        source_facts = ctx.working_memory.get("source_facts")
        source_facts = dict(source_facts) if isinstance(source_facts, dict) else {}
        if not items_in:
            items_from_briefs = [{"knowledge_point": kp} for kp in source_briefs.keys() if str(kp or "").strip()]
            items_from_facts = [{"knowledge_point": kp} for kp in source_facts.keys() if str(kp or "").strip()]
            items_in = items_from_briefs or items_from_facts
        outlines = ctx.working_memory.get("outlines")
        outlines = dict(outlines) if isinstance(outlines, dict) else {}
        knowledge_types = ctx.working_memory.get("knowledge_types")
        knowledge_types = dict(knowledge_types) if isinstance(knowledge_types, dict) else {}

        sections: List[Dict[str, Any]] = []
        for item in items_in[:max_points]:
            kp = str(item.get("knowledge_point") or "").strip()
            if not kp:
                continue

            wiki = item.get("wikipedia") if isinstance(item.get("wikipedia"), dict) else {}
            mw = item.get("mediawiki") if isinstance(item.get("mediawiki"), dict) else {}
            web = item.get("web_search") if isinstance(item.get("web_search"), dict) else {}
            pages_blob = item.get("web_pages") if isinstance(item.get("web_pages"), dict) else {}
            gh = item.get("github") if isinstance(item.get("github"), dict) else {}
            se = item.get("stackexchange") if isinstance(item.get("stackexchange"), dict) else {}
            q = item.get("questions") if isinstance(item.get("questions"), dict) else {}

            web_provider = str(web.get("provider") or "").strip()
            web_scope = str(web.get("scope") or "").strip()
            web_summary = str(web.get("summary") or "").strip()
            web_results = web.get("results") if isinstance(web.get("results"), list) else []
            web_results = [r for r in web_results if isinstance(r, dict)][:max_web_results]

            web_pages = pages_blob.get("pages") if isinstance(pages_blob.get("pages"), list) else []
            web_pages = [p for p in web_pages if isinstance(p, dict)]
            web_pages = [p for p in web_pages if p.get("success") and str(p.get("text") or "").strip()]
            for p in web_pages:
                p["text"] = _clip_text(str(p.get("text") or ""), max_page_chars)
            web_pages = web_pages[:max_web_pages]

            examples = q.get("examples") if isinstance(q.get("examples"), list) else []
            exercises = q.get("exercises") if isinstance(q.get("exercises"), list) else []
            if not with_questions:
                examples = []
                exercises = []

            kt_obj = knowledge_types.get(kp) if isinstance(knowledge_types.get(kp), dict) else {}
            knowledge_type = str(kt_obj.get("knowledge_type") or "").strip().lower()
            if knowledge_type not in _KNOWLEDGE_TYPE_VALUES:
                knowledge_type = _heuristic_knowledge_type(kp)

            brief = source_briefs.get(kp) if isinstance(source_briefs.get(kp), dict) else {}
            if not brief:
                wiki_summary = _clip_text(str(wiki.get("summary") or wiki.get("content") or ""), 1200)
                web_sum = _clip_text(web_summary, 1400)
                brief = {
                    "definition": [x for x in [wiki_summary.split("\n")[0] if wiki_summary else ""] if x],
                    "core_ideas": [x for x in [web_sum] if x],
                    "key_properties": [],
                    "conditions_and_boundaries": [],
                    "common_misconceptions": [],
                    "applications": [],
                    "derivation_or_proof_sketch": [],
                    "notation_and_terms": [],
                }

            facts_raw = source_facts.get(kp)
            facts_list = facts_raw if isinstance(facts_raw, list) else []
            facts: List[Dict[str, Any]] = []
            for f in facts_list[:16]:
                if not isinstance(f, dict):
                    continue
                fact = str(f.get("fact") or "").strip()
                if not fact:
                    continue
                try:
                    conf = float(f.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    conf = 0.0
                facts.append({"fact": _clip_text(fact, 180), "confidence": max(0.0, min(conf, 1.0))})

            outline = outlines.get(kp) if isinstance(outlines.get(kp), dict) else {}
            outline_sections = outline.get("sections") if isinstance(outline.get("sections"), list) else []
            outline_sections = [x for x in outline_sections if isinstance(x, dict)]
            if not outline_sections:
                outline_sections = _default_outline_sections(knowledge_type, preset)

            # Section-level parallel writing.
            sem = asyncio.Semaphore(section_concurrency)

            async def _write_section(sec: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any], int]:
                title = str(sec.get("title") or "").strip().strip("# ").strip() or "本节"
                hints = sec.get("hints")
                verify = sec.get("verify")
                hints_list = [str(x).strip() for x in hints if str(x).strip()] if isinstance(hints, list) else []
                verify_list = [str(x).strip() for x in verify if str(x).strip()] if isinstance(verify, list) else []

                # Fallback when LLM isn't available.
                if not is_llm_configured():
                    lines = [f"#### {title}"]
                    for h in hints_list[:4]:
                        lines.append(f"- {h}")
                    # Use a few brief signals so the output isn't empty.
                    if not hints_list:
                        for k in [
                            "definition",
                            "core_ideas",
                            "key_properties",
                            "conditions_and_boundaries",
                            "common_misconceptions",
                            "applications",
                        ]:
                            v = brief.get(k)
                            if isinstance(v, list) and v:
                                lines.append(f"- {str(v[0]).strip()}")
                    return ("\n".join(lines).strip(), "fallback", {}, 0)

                plan_summary = ctx.working_memory.get("plan_summary")
                plan_summary_obj = dict(plan_summary) if isinstance(plan_summary, dict) else {}
                # Keep only the most useful keys (avoid inflating the prompt).
                plan_summary_obj = {
                    "topic": str(plan_summary_obj.get("topic") or "").strip(),
                    "subject": str(plan_summary_obj.get("subject") or "").strip(),
                    "preset": str(plan_summary_obj.get("preset") or "").strip(),
                    "requirements": _clip_text(str(plan_summary_obj.get("requirements") or ""), 500),
                    "knowledge_points": plan_summary_obj.get("knowledge_points")
                    if isinstance(plan_summary_obj.get("knowledge_points"), list)
                    else [],
                }

                completed_overview = _collect_completed_overview(
                    ctx,
                    current_kp=kp,
                    local_sections=sections,
                    limit=8,
                )

                semantic_memory_raw = ctx.working_memory.get("semantic_memory")
                semantic_memory: List[Dict[str, Any]] = []
                if isinstance(semantic_memory_raw, list):
                    for it in semantic_memory_raw[:8]:
                        if not isinstance(it, dict):
                            continue
                        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
                        semantic_memory.append(
                            {
                                "subject": _clip_text(str(meta.get("subject") or ""), 48),
                                "topic": _clip_text(str(meta.get("topic") or ""), 72),
                                "knowledge_point": _clip_text(str(meta.get("knowledge_point") or ""), 72),
                                "summary": _clip_text(str(it.get("text") or ""), 320),
                            }
                        )
                semantic_memory = [x for x in semantic_memory if str(x.get("summary") or "").strip()][:5]

                payload = {
                    "topic": topic,
                    "subject": subject,
                    "knowledge_point": kp,
                    "knowledge_type": knowledge_type,
                    "grade_band": grade_band,
                    "curriculum_context": curriculum_context,
                    "preset": preset,
                    "ability_level": str(ctx.user_profile.ability_level or "unknown"),
                    "ability_score": float(ctx.user_profile.ability_score or 0.5),
                    "requirements": requirements,
                    "plan_summary": plan_summary_obj,
                    "completed_overview": completed_overview,
                    "semantic_memory": semantic_memory,
                    "source_brief": brief,
                    "source_facts": facts,
                    "section": {"title": title, "hints": hints_list[:6], "verify": verify_list[:8]},
                    "instructions": [
                        "Write only the body content for this one section.",
                        "Do not output any heading line or `####`; the system will add the title.",
                        "你可以自由组织段落/列表，不需要固定模板；优先清晰、可执行、便于自学。",
                        "Do not output #/##/### headings. Do not output references, external links, URLs, or evidence markers such as [[1]].",
                        "All wording must be original synthesis and rewriting. Do not copy or paste source_brief or other source text.",
                        "If source_facts contain low-confidence facts (confidence < 0.6), frame the corresponding statements as inference/possible/suggested in the user's language instead of strong assertions.",
                        "If information is insufficient, explicitly mark it as inference or suggestion in the user's language.",
                        "Mathematical expressions must use LaTeX delimiters: inline `$...$` and display `$$...$$`; never leave half-written formulas.",
                        "Adapt the structure to knowledge_type: algorithm/procedure sections must give ordered steps; theorem/definition sections must state conditions, conclusion, and at least one minimal example; application sections must include a worked mini-example.",
                        "Respect curriculum_context and grade_band: keep explanations within in_scope, avoid out_of_scope content, assume prerequisites rather than reteaching them, and match depth to the stated school stage.",
                        "Do not leave unresolved placeholders such as `{variable}`, dangling Markdown tables, or unclosed code fences.",
                        "If completed_overview is non-empty, treat it as an overview of already explained content. Avoid repeating covered definitions/properties; if review is needed, use one sentence to connect with the prior explanation.",
                        "If semantic_memory is non-empty, it contains historical generated-content fragments. Use it to maintain terminology, symbols, or narrative rhythm and avoid cross-task repetition; when necessary, state the connection or difference in one sentence.",
                    ],
                }

                async with sem:
                    res = await self._call_llm_markdown_with_continuation(
                        messages=[
                            {"role": "system", "content": _section_writer_system_prompt()},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                        ],
                        model=writer_model,
                        temperature=0.25,
                        max_tokens=section_max_tokens,
                        continuation_context={
                            "topic": topic,
                            "subject": subject,
                            "knowledge_point": kp,
                            "section_title": title,
                        },
                        max_continuations=cont_limit,
                        raise_on_fail=strict_llm,
                    )
                md = str(res.get("content") or "").strip()
                md = _sanitize_explanation_markdown(md, knowledge_point=kp)
                md = md.lstrip()
                if md.startswith("####"):
                    md = "\n".join(md.splitlines()[1:]).lstrip()
                md = f"#### {title}\n\n{md}".strip() if md else f"#### {title}"
                finish_reason = str(res.get("finish_reason") or "").strip()
                usage = res.get("usage") if isinstance(res.get("usage"), dict) else {}
                try:
                    conts = int(res.get("continuations") or 0)
                except (TypeError, ValueError):
                    conts = 0
                return (md, finish_reason, usage, conts)

            def _ensure_revision_shape(markdown: str) -> str:
                md = _sanitize_explanation_markdown(str(markdown or "").strip(), knowledge_point=kp)
                if not md:
                    return ""
                if re.search(r"^\s{0,3}####\s+", md, flags=re.M):
                    return md
                if len(outline_sections) == 1:
                    title = str(outline_sections[0].get("title") or "").strip().strip("# ").strip() or "本节"
                    return f"#### {title}\n\n{md}".strip()
                return md

            async def _write_draft() -> Dict[str, Any]:
                section_results = await asyncio.gather(*[_write_section(sec) for sec in outline_sections])

                md_parts: List[str] = []
                finish_reasons: List[str] = []
                usage_sum: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                cont_sum = 0
                any_llm = False
                for md, fr, usage, conts in section_results:
                    if md:
                        md_parts.append(md)
                    if fr:
                        finish_reasons.append(fr)
                    if isinstance(usage, dict):
                        for k in ["prompt_tokens", "completion_tokens", "total_tokens"]:
                            raw_val = usage.get(k)
                            try:
                                n = int(raw_val or 0)
                            except (TypeError, ValueError):
                                n = 0
                            usage_sum[k] += n
                    cont_sum += int(conts or 0)
                    if str(fr or "").strip().lower() not in {"", "fallback"}:
                        any_llm = True

                draft_md = "\n\n".join([x.strip() for x in md_parts if x.strip()]).strip()
                draft_md = _sanitize_explanation_markdown(draft_md, knowledge_point=kp)
                finish_reason = (
                    "length" if any((x or "").strip().lower() == "length" for x in finish_reasons) else "stop"
                )
                return {
                    "markdown": draft_md,
                    "finish_reason": finish_reason,
                    "usage": {k: v for k, v in usage_sum.items() if v},
                    "continuations": cont_sum,
                    "source": "writer_agent" if any_llm else "fallback",
                }

            async def _review_draft(markdown: str) -> Dict[str, Any]:
                md = str(markdown or "").strip()
                if not md:
                    return {
                        "passed": False,
                        "issues": [f"知识点《{kp}》未生成可用正文"],
                        "suggestions": ["重新生成该知识点正文"],
                        "source": "heuristic",
                    }
                if not is_llm_configured():
                    return {"passed": True, "issues": [], "suggestions": [], "source": "heuristic"}

                review_payload = {
                    "topic": topic,
                    "subject": subject,
                    "knowledge_point": kp,
                    "preset": preset,
                    "requirements": requirements,
                    "knowledge_type": knowledge_type,
                    "grade_band": grade_band,
                    "curriculum_context": curriculum_context,
                    "outline_sections": outline_sections,
                    "source_brief": brief,
                    "source_facts": facts,
                    "markdown": md,
                    "instructions": [
                        "You are the reviewer agent for this knowledge-point writing stage.",
                        "Review only this knowledge point body, not the whole document.",
                        "重点检查：是否满足 outline_sections 的 verify 意图；定义/条件/边界/误区/应用是否与知识类型匹配；是否与 source_facts 矛盾；是否存在空泛重复。",
                        "Check that the draft respects curriculum_context and grade_band boundaries.",
                        "passed=true means the section can enter assembly. passed=false means you must provide specific executable issues.",
                        'Output strict JSON: {"passed": bool, "issues": [string], "suggestions": [string]}.',
                    ],
                }
                raw = await self._call_llm_text(
                    messages=[
                        {"role": "system", "content": _section_reviewer_system_prompt()},
                        {"role": "user", "content": json.dumps(review_payload, ensure_ascii=False)},
                    ],
                    model=writer_model,
                    temperature=0.1,
                    max_tokens=900,
                    response_format={"type": "json_object"},
                    raise_on_fail=strict_llm,
                )
                obj = self._extract_json_obj(str(raw or ""))
                if strict_llm and not obj:
                    raise RuntimeError(f"writer_review_failed: invalid_json knowledge_point={kp}")
                if not obj:
                    return {"passed": True, "issues": [], "suggestions": [], "source": "invalid_json_fallback"}
                return {
                    "passed": bool(obj.get("passed")) if "passed" in obj else True,
                    "issues": [str(x or "").strip() for x in obj.get("issues", []) if str(x or "").strip()]
                    if isinstance(obj.get("issues"), list)
                    else [],
                    "suggestions": [
                        str(x or "").strip() for x in obj.get("suggestions", []) if str(x or "").strip()
                    ]
                    if isinstance(obj.get("suggestions"), list)
                    else [],
                    "source": "llm",
                }

            async def _revise_draft(markdown: str, review: Dict[str, Any]) -> str:
                if not is_llm_configured():
                    return markdown
                revise_payload = {
                    "topic": topic,
                    "subject": subject,
                    "knowledge_point": kp,
                    "preset": preset,
                    "requirements": requirements,
                    "grade_band": grade_band,
                    "curriculum_context": curriculum_context,
                    "outline_sections": outline_sections,
                    "source_brief": brief,
                    "source_facts": facts,
                    "review": {
                        "issues": list(review.get("issues") or [])[:12],
                        "suggestions": list(review.get("suggestions") or [])[:12],
                    },
                    "markdown": markdown,
                    "instructions": [
                        "You are the revision agent for this knowledge-point writing stage.",
                        "Revise only this knowledge point body and directly output the complete revised Markdown.",
                        "保留并修正原有 #### 小节结构；如需要，可补充短段落或列表。",
                        "Modify only according to review.issues. Do not introduce a new references section, URLs, or whole-document title.",
                        "Keep the revision aligned with curriculum_context and grade_band; do not add out_of_scope content.",
                        "The revision must be more specific than the original, especially by filling in flagged conditions, boundaries, misconceptions, or applications.",
                    ],
                }
                revised = await self._call_llm_text(
                    messages=[
                        {"role": "system", "content": _section_revision_system_prompt()},
                        {"role": "user", "content": json.dumps(revise_payload, ensure_ascii=False)},
                    ],
                    model=writer_model,
                    temperature=0.2,
                    max_tokens=max(1800, min(section_max_tokens * max(1, len(outline_sections)) + 800, 8000)),
                    raise_on_fail=strict_llm,
                )
                revised_md = _ensure_revision_shape(str(revised or ""))
                return revised_md or markdown

            async def _emit_writer_status(content: str) -> None:
                emit = getattr(self, "_emit_status", None)
                if callable(emit):
                    await emit(content)

            writer_agent = _KnowledgePointWriterAgent(
                knowledge_point=kp,
                plan={"sections": outline_sections, "knowledge_type": knowledge_type},
                write_draft=_write_draft,
                review_draft=_review_draft,
                revise_draft=_revise_draft,
                max_revision_rounds=writer_revision_rounds,
                emit_status=_emit_writer_status,
            )
            writer_result = await writer_agent.run()

            explanation_md = _ensure_revision_shape(writer_result.markdown)
            explanation_source = writer_result.source
            explanation_finish_reason = writer_result.finish_reason
            explanation_usage: Dict[str, Any] = dict(writer_result.usage or {})
            cont_sum = int(writer_result.continuations or 0)

            diagram = _first_existing_diagram(ctx, kp)

            sections.append(
                {
                    "knowledge_point": kp,
                    "explanation_markdown": explanation_md,
                    "explanation_source": explanation_source,
                    "explanation_finish_reason": explanation_finish_reason,
                    "explanation_usage": explanation_usage,
                    "explanation_continuations": cont_sum,
                    "writer_agent": {
                        "mode": "knowledge_point",
                        "revisions": int(writer_result.revisions or 0),
                        "review": writer_result.review,
                        "actions": writer_result.actions,
                    },
                    "wikipedia": wiki,
                    "mediawiki": mw,
                    "web_provider": web_provider,
                    "web_scope": web_scope,
                    "web_summary": web_summary,
                    "diagram": diagram,
                    "web_results": web_results,
                    "web_pages": web_pages,
                    "github": gh,
                    "stackexchange": se,
                    "examples": examples,
                    "exercises": exercises,
                }
            )

        return {
            "topic": topic,
            "subject": subject,
            "preset": preset,
            "requirements": requirements,
            "sections": sections,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
