from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Tuple

from backend.agent.tools.text_utils import _sanitize_explanation_markdown
from backend.agent.types import CompressedContext
from backend.core.llm_client import is_llm_configured
from backend.core.settings import MAIN_MODEL


def _clip_text(text: str, limit: int) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "…"


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

    if any(
        x in s for x in ["定理", "命题", "引理", "推论", "结论", "定律", "法则", "公式", "恒等式", "不等式", "方程"]
    ):
        return "theorem"

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

    if any(x in s for x in ["定义", "是什么", "含义", "概念", "记号", "符号", "术语"]):
        return "definition"
    return "concept"


def _default_outline_sections(knowledge_type: str, preset: str) -> List[Dict[str, Any]]:
    """A minimal outline fallback used when outline tool isn't called or LLM isn't configured.

    The goal is to keep the pipeline usable without forcing a rigid template across knowledge points.
    """

    kt = (knowledge_type or "").strip().lower()
    if kt not in {"definition", "theorem", "algorithm", "concept", "history", "experiment"}:
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
            if knowledge_type not in {"definition", "theorem", "algorithm", "concept", "history", "experiment"}:
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
                except Exception:
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
                "ability_level": str(ctx.user_profile.ability_level or "unknown"),
                "ability_score": float(ctx.user_profile.ability_score or 0.5),
                "requirements": requirements,
                "source_brief": brief,
                "source_facts": facts,
                "constraints": [
                    "请为该知识点设计一份『讲解结构提纲』，用于后续分段写作。",
                    f"sections 数量建议：{sec_min}~{sec_max} 个（不必凑满，但要覆盖核心内容）。",
                    '输出严格 JSON：{"sections":[{"title":"...","hints":["..."],"verify":["..."]}, ...]}。',
                    "title 用中文短语，避免机械复用固定模板标题；要体现本知识点特点。",
                    "hints 每节 1~4 条，短提示即可。",
                    "verify 为该节写完后的『验证标准』，每节 2~5 条，越可操作越好。",
                    "尽量覆盖：定义/表述、直观理解、关键结论或性质/条件、常见误区、应用/解题框架或总结。允许合并/拆分；不适用可省略，但请在 verify 中体现覆盖意图或说明省略/替代。",
                    "如提供了 source_facts：请在 verify 中加入 1~2 条『与关键事实一致/不矛盾』的校验点；低置信度事实需提示为推断。",
                    "不要输出例题/练习题；不要输出 URL；不要输出 Markdown。",
                ],
            }

            raw = await self._call_llm_text(
                messages=[
                    {"role": "system", "content": "你是严谨的教学结构设计助手，只输出 JSON。"},
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

        topic = str(args.get("topic") or aggregated.get("topic") or ctx.current_task).strip()
        subject = str(
            args.get("subject") or aggregated.get("subject") or ctx.user_profile.preferences.get("subject") or ""
        ).strip()
        items_in = aggregated.get("items") if isinstance(aggregated.get("items"), list) else []
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

        section_conc_raw = args.get("section_concurrency") or os.getenv("STUDY_MATERIALS_SECTION_CONCURRENCY") or "3"
        try:
            section_concurrency = int(section_conc_raw)
        except Exception:
            section_concurrency = 3
        section_concurrency = max(1, min(section_concurrency, 6))

        if strict_llm and not is_llm_configured():
            raise RuntimeError("llm_not_configured")

        writer_model = str(
            os.getenv("STUDY_MATERIALS_WRITER_MODEL")
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
            if knowledge_type not in {"definition", "theorem", "algorithm", "concept", "history", "experiment"}:
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
                except Exception:
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

                payload = {
                    "topic": topic,
                    "subject": subject,
                    "knowledge_point": kp,
                    "knowledge_type": knowledge_type,
                    "preset": preset,
                    "ability_level": str(ctx.user_profile.ability_level or "unknown"),
                    "ability_score": float(ctx.user_profile.ability_score or 0.5),
                    "requirements": requirements,
                    "source_brief": brief,
                    "source_facts": facts,
                    "section": {"title": title, "hints": hints_list[:6], "verify": verify_list[:8]},
                    "instructions": [
                        "请只撰写这一个小节的正文内容。",
                        "不要输出任何标题行（不要输出 `####`）；标题会由系统统一添加。",
                        "你可以自由组织段落/列表，不需要固定模板；优先清晰、可执行、便于自学。",
                        "不要输出 #/##/### 标题；不要输出参考资料/外部链接；不要输出任何 URL；不要输出证据标记（如 [[1]]）。",
                        "所有表述必须为原创综合与改写，严禁照抄 source_brief 或其他来源原文。",
                        "若 source_facts 中存在低置信度事实（confidence<0.6），对应表述必须使用「推断/可能/建议」等措辞避免强断言。",
                        "若信息不足，请明确标注「推断」或「建议」。",
                    ],
                }

                async with sem:
                    res = await self._call_llm_markdown_with_continuation(
                        messages=[
                            {
                                "role": "system",
                                "content": "你是严谨的自学资料编写老师。所有讲解必须为原创改写与综合，严禁直接搬运或拼贴来源文本。输出必须是 Markdown。",
                            },
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
                except Exception:
                    conts = 0
                return (md, finish_reason, usage, conts)

            tasks = [_write_section(sec) for sec in outline_sections]
            section_results = await asyncio.gather(*tasks)

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
                        except Exception:
                            n = 0
                        usage_sum[k] += n
                cont_sum += int(conts or 0)
                if fr:
                    any_llm = True

            explanation_md = "\n\n".join([x.strip() for x in md_parts if x.strip()]).strip()
            explanation_md = _sanitize_explanation_markdown(explanation_md, knowledge_point=kp)

            explanation_source = "llm_sectioned" if any_llm else "fallback"
            explanation_finish_reason = (
                "length" if any((x or "").strip().lower() == "length" for x in finish_reasons) else "stop"
            )
            explanation_usage: Dict[str, Any] = {k: v for k, v in usage_sum.items() if v}

            diagram = _first_existing_diagram(ctx, kp)

            sections.append(
                {
                    "knowledge_point": kp,
                    "explanation_markdown": explanation_md,
                    "explanation_source": explanation_source,
                    "explanation_finish_reason": explanation_finish_reason,
                    "explanation_usage": explanation_usage,
                    "explanation_continuations": cont_sum,
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
