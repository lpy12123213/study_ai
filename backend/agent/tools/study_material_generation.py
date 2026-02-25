from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.agent.tools.text_utils import _sanitize_explanation_markdown
from backend.agent.types import CompressedContext
from backend.core.settings import LESSON_PLAN_API_KEY, MOONSHOT_API_KEY


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
    if any(x in s for x in ["定理", "命题", "引理", "推论"]):
        return "theorem"
    if any(x in s for x in ["算法", "排序", "搜索", "动态规划", "贪心", "回溯"]):
        return "algorithm"
    if any(x in s for x in ["实验", "测量", "装置", "观测"]):
        return "experiment"
    if any(x in s for x in ["历史", "发展", "人物", "年代", "起源"]):
        return "history"
    if any(x in s for x in ["定义", "是什么", "含义"]):
        return "definition"
    return "concept"


def _default_outline_sections(knowledge_type: str, preset: str) -> List[Dict[str, Any]]:
    """A deterministic outline fallback used when outline tool isn't called or LLM isn't configured."""

    kt = (knowledge_type or "").strip().lower()
    if kt not in {"definition", "theorem", "algorithm", "concept", "history", "experiment"}:
        kt = "concept"

    deep = preset in {"deep", "research"}
    research = preset == "research"

    def sec(title: str, hints: List[str], verify: List[str]) -> Dict[str, Any]:
        return {"title": title, "hints": hints[:4], "verify": verify[:5]}

    if kt == "theorem":
        sections = [
            sec("定理陈述（先写清条件）", ["用一句话说清楚结论是什么", "把所有适用条件显式写出"], ["出现“条件/结论”拆分", "不遗漏边界条件"]),
            sec("直观理解（为什么可能成立）", ["用图像/类比解释直觉", "解释结论在极端情况下是否合理"], ["有直观解释，不是纯符号复述"]),
            sec("条件与边界/反例", ["哪些条件不可缺？缺了会怎样？", "给出典型反例或边界情况"], ["至少1个边界/反例或陷阱"]),
            sec("证明思路骨架（选读）" if deep else "证明思路（可跳过）", ["给出3~8行推导骨架", "标注关键一步为什么这么做"], ["不要求写满细节，但要可追踪"]),
            sec("常见误区与易错点", ["列出3个常见误解", "解释为什么会错"], ["至少2条误区（若适用）"]),
            sec("应用/题型与解题框架", ["遇到题目时怎么用", "常用变形/等价表述"], ["给出可执行的步骤/框架"]),
        ]
        if research:
            sections.append(sec("自检清单", ["列出5个学完应能回答的问题"], ["有可操作自检项"]))
        return sections

    if kt == "algorithm":
        sections = [
            sec("要解决的问题与适用场景", ["这个算法解决什么问题", "输入/输出是什么"], ["说明适用范围"]),
            sec("核心思想（直觉）", ["一句话概括策略", "用例子说明为什么这样做"], ["有直觉说明"]),
            sec("步骤/伪代码", ["分步骤列出流程", "关键状态/变量含义"], ["步骤清晰可执行"]),
            sec("正确性要点（为什么对）", ["说明关键不变式/贪心选择理由"], ["给出正确性理由"]),
            sec("复杂度与瓶颈", ["时间复杂度/空间复杂度", "最坏/平均情况（如适用）"], ["复杂度明确"]),
            sec("实现细节与常见坑", ["边界条件", "容易写错的地方"], ["至少2个实现坑"]),
        ]
        if deep:
            sections.append(sec("变体与拓展（选读）", ["有哪些常见变体", "何时选择变体"], ["至少提到1个变体（如适用）"]))
        return sections

    if kt == "history":
        sections = [
            sec("它是什么（一句话概括）", ["先给出结论式摘要"], ["有一句话概括"]),
            sec("时间线/发展脉络", ["按时间或阶段描述", "点出关键转折"], ["至少3个关键节点"]),
            sec("关键人物/事件/思想", ["列出核心贡献", "避免八卦式细节"], ["有关键贡献点"]),
            sec("影响与今天怎么看", ["它解决了什么问题", "留下了什么方法/观点"], ["有影响总结"]),
        ]
        return sections

    if kt == "experiment":
        sections = [
            sec("实验目的与核心结论", ["要验证/测量什么", "预期观察到什么"], ["目的明确"]),
            sec("装置与变量", ["装置结构", "自变量/因变量/控制变量"], ["变量划分清晰"]),
            sec("步骤与数据处理", ["流程步骤", "如何计算/拟合/作图"], ["步骤可复现"]),
            sec("误差来源与注意事项", ["系统误差/随机误差", "如何减小误差"], ["至少2个误差来源"]),
        ]
        return sections

    # concept / definition
    sections = [
        sec("为什么需要它（动机）", ["它解决什么问题", "没有它会怎样"], ["有动机说明"]),
        sec("定义与核心表述", ["给出严格定义/核心公式", "解释每个术语/符号含义"], ["定义清晰且自洽"]),
        sec("直观理解（类比/图像）", ["用类比帮助理解", "给一个最简单例子"], ["有直觉+例子"]),
        sec("关键性质/结论", ["列出3~6条性质", "每条写清适用条件（若有）"], ["性质不少于3条（若适用）"]),
        sec("常见误区与易错点", ["误区→为何错→正确理解"], ["至少2条误区（若适用）"]),
        sec("应用/解题框架", ["遇到相关问题怎么用", "常用思路2~4步"], ["给出可执行步骤"]),
    ]
    if deep:
        sections.append(sec("推导/证明思路（选读）", ["给出推导骨架或证明框架"], ["有推导骨架（如适用）"]))
    if research:
        sections.append(sec("自检清单（选读）", ["列出5个自测问题"], ["有自检项"]))
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
                return (5, 7)
            if preset == "deep":
                return (8, 11)
            if preset == "research":
                return (9, 13)
            return (6, 9)

        sec_min, sec_max = _sec_bounds()

        async def _outline_one(kp: str) -> Dict[str, Any]:
            kt_obj = knowledge_types.get(kp) if isinstance(knowledge_types.get(kp), dict) else {}
            knowledge_type = str(kt_obj.get("knowledge_type") or "").strip().lower()
            if knowledge_type not in {"definition", "theorem", "algorithm", "concept", "history", "experiment"}:
                knowledge_type = _heuristic_knowledge_type(kp)

            brief = source_briefs.get(kp) if isinstance(source_briefs.get(kp), dict) else {}

            if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                if strict_llm:
                    raise RuntimeError("llm_not_configured")
                outline = {"sections": _default_outline_sections(knowledge_type, preset)}
                ctx.working_memory.setdefault("outlines", {})[kp] = outline
                return {"knowledge_point": kp, "outline": outline, "source": "heuristic", "knowledge_type": knowledge_type}

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
                "constraints": [
                    "请为该知识点设计一份『讲解结构提纲』，用于后续分段写作。",
                    f"sections 数量建议：{sec_min}~{sec_max} 个（不必凑满，但要覆盖核心内容）。",
                    "输出严格 JSON：{\"sections\":[{\"title\":\"...\",\"hints\":[\"...\"],\"verify\":[\"...\"]}, ...]}。",
                    "title 用中文短语，避免机械复用固定模板标题；要体现本知识点特点。",
                    "hints 每节 1~4 条，短提示即可。",
                    "verify 为该节写完后的『验证标准』，每节 2~5 条，越可操作越好。",
                    "必须覆盖：定义/表述、直观理解、关键结论或性质/条件、常见误区、应用/解题框架或总结。",
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
        subject = str(args.get("subject") or aggregated.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
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

        if strict_llm and not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            raise RuntimeError("llm_not_configured")

        writer_model = str(
            os.getenv("STUDY_MATERIALS_WRITER_MODEL")
            or getattr(getattr(self, "config", None), "planner_model", "")
            or getattr(getattr(self, "config", None), "summarizer_model", "")
        ).strip()
        if not writer_model:
            writer_model = "gpt-4o-mini"

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
                if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                    lines = [f"#### {title}"]
                    for h in hints_list[:4]:
                        lines.append(f"- {h}")
                    # Use a few brief signals so the output isn't empty.
                    if not hints_list:
                        for k in ["definition", "core_ideas", "key_properties", "conditions_and_boundaries", "common_misconceptions", "applications"]:
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
                    "section": {"title": title, "hints": hints_list[:6], "verify": verify_list[:8]},
                    "instructions": [
                        "请只撰写这一个小节的内容。",
                        f"输出必须以 `#### {title}` 开头。",
                        "不要输出 #/##/### 标题；不要输出参考资料/外部链接；不要输出任何 URL；不要输出证据标记（如 [[1]]）。",
                        "所有表述必须为原创综合与改写，严禁照抄 source_brief 或其他来源原文。",
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
                        continuation_context={"topic": topic, "subject": subject, "knowledge_point": kp, "section_title": title},
                        max_continuations=cont_limit,
                        raise_on_fail=strict_llm,
                    )
                md = str(res.get("content") or "").strip()
                md = _sanitize_explanation_markdown(md, knowledge_point=kp)
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
                        try:
                            usage_sum[k] += int(usage.get(k) or 0)
                        except Exception:
                            pass
                cont_sum += int(conts or 0)
                if fr:
                    any_llm = True

            explanation_md = "\n\n".join([x.strip() for x in md_parts if x.strip()]).strip()
            explanation_md = _sanitize_explanation_markdown(explanation_md, knowledge_point=kp)

            explanation_source = "llm_sectioned" if any_llm else "fallback"
            explanation_finish_reason = "length" if any((x or "").strip().lower() == "length" for x in finish_reasons) else "stop"
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

