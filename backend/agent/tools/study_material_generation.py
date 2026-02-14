from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.agent.tools.text_utils import _sanitize_explanation_markdown
from backend.agent.types import CompressedContext
from backend.core.settings import LESSON_PLAN_API_KEY, MOONSHOT_API_KEY


class StudyMaterialGenerationToolsMixin:
    async def _tool_generate_study_material(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """基于聚合数据，为每个知识点生成讲解与例题解答。"""

        aggregated = ctx.working_memory.get("aggregate_knowledge") or ctx.working_memory.get("aggregated")
        if not isinstance(aggregated, dict):
            aggregated = {}

        topic = str(args.get("topic") or aggregated.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or aggregated.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        sections_in = aggregated.get("items") if isinstance(aggregated.get("items"), list) else []

        # Study-materials options (passed from API -> TaskManager -> AgentCore).
        # Planner already uses these flags; here we also use them to shape writing style/length.
        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        strict_llm = self._strict_llm(ctx, args)
        if strict_llm and not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            raise RuntimeError("llm_not_configured")
        preset = str(args.get("preset") or study_opts.get("preset") or "standard").strip().lower() or "standard"
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = "standard"
        requirements = str(args.get("requirements") or study_opts.get("requirements") or "").strip()
        if len(requirements) > 600:
            requirements = requirements[:599].rstrip() + "…"

        # Optional: generate only for specified knowledge points (useful when running per-point subagents).
        requested_points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            requested_points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if requested_points:
            requested_set = {p for p in requested_points}
            sections_in = [
                it
                for it in (sections_in or [])
                if isinstance(it, dict) and str(it.get("knowledge_point") or "").strip() in requested_set
            ]

        max_points = max(1, min(int(args.get("max_points") or 8), 15))
        max_examples = max(0, min(int(args.get("max_examples") or 1), 2))
        max_web_results = max(3, min(int(args.get("max_web_results") or 8), 25))
        max_web_pages = max(0, min(int(args.get("max_web_pages") or 2), 8))
        max_page_chars = max(500, min(int(args.get("max_page_chars") or 3200), 8000))
        with_diagrams = bool(args.get("with_diagrams", True))
        with_questions = bool(args.get("with_questions", False))
        max_diagrams = int(
            args.get("max_diagrams")
            or (4 if preset == "deep" else 6 if preset == "research" else 3 if preset == "standard" else 1)
        )
        # Upper bound only; the model is still instructed to output 0~1 unless multiple diagrams truly help.
        max_diagrams = max(0, min(max_diagrams, 20))

        sections: List[Dict[str, Any]] = []
        for item in (sections_in or [])[:max_points]:
            if not isinstance(item, dict):
                continue
            kp = str(item.get("knowledge_point") or "").strip()
            if not kp:
                continue

            writer_model = str(
                os.getenv("STUDY_MATERIALS_WRITER_MODEL")
                or self.config.planner_model
                or self.config.summarizer_model
            ).strip()
            writer_reasoning = None
            writer_max_tokens_raw = str(os.getenv("STUDY_MATERIALS_WRITER_MAX_TOKENS") or "").strip()
            try:
                writer_max_tokens = int(writer_max_tokens_raw) if writer_max_tokens_raw else 0
            except Exception:
                writer_max_tokens = 0
            # "Infinite" (requested): use a very large max_tokens so generation isn't artificially truncated.
            if writer_max_tokens <= 0:
                writer_max_tokens = 200000

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
            web_pages = web_pages[:max_web_pages]

            examples = q.get("examples") if isinstance(q.get("examples"), list) else []
            exercises = q.get("exercises") if isinstance(q.get("exercises"), list) else []
            examples = [x for x in examples if isinstance(x, dict)][: max_examples or 0]
            exercises = [x for x in exercises if isinstance(x, dict)][:10]
            if not with_questions:
                examples = []
                exercises = []

            # Explanation (LLM if configured; fallback to Wikipedia summary)
            explanation_md = ""
            explanation_source = "unknown"
            explanation_finish_reason = ""
            explanation_usage: Dict[str, Any] = {}
            explanation_continuations = 0

            if LESSON_PLAN_API_KEY or MOONSHOT_API_KEY:

                def _clip_text(text: str, limit_chars: int) -> str:
                    t = (text or "").strip()
                    if len(t) <= limit_chars:
                        return t
                    return t[: limit_chars - 1].rstrip() + "…"

                fallback_template_lines = [
                    "#### 为什么需要它（动机与问题背景）",
                    "  - 这个概念/方法要解决什么问题？没有它会怎样？",
                    "  - 用一句话概括它的核心价值",
                    "#### 定义与核心表述",
                    "  - 给出精确定义（含符号约定）",
                    "  - 用「一句话版本」帮助记忆",
                    "#### 直观理解（类比与图像）",
                    "  - 用日常生活或已学知识做类比，让读者先建立直觉",
                    '  - 描述"脑中的画面"：如果要画一张图，应该画什么？',
                    "#### 关键结论与性质",
                    "  - 列出最重要的 3~6 条结论（写清适用条件）",
                    "  - 每条结论用**加粗**突出核心表述",
                    "  - 给出「何时用 / 怎么用」的简要提示",
                    "#### 常见误区与易错点",
                    "  - 误区描述 → 为什么会错 → 正确理解 / 反例",
                    "  - 重点标注「看起来对但实际错」的陷阱",
                    "#### 解题/应用思路小结",
                    "  - 遇到相关问题时的思考框架（2~4 步）",
                    "  - 常用技巧或判断依据",
                ]
                if preset in {"deep", "research"}:
                    fallback_template_lines.extend(
                        [
                            "#### 推导/证明思路（选读）",
                            "  - 给出 3~8 行的证明框架或推导骨架",
                            "  - 标注关键步骤的「为什么这样做」",
                            "#### 联系与拓展（选读）",
                            "  - 前置知识：理解本概念需要先掌握什么？",
                            "  - 相邻概念：与哪些概念容易混淆或有紧密联系？",
                            "  - 典型应用场景举例",
                        ]
                    )
                if preset == "research":
                    fallback_template_lines.extend(
                        [
                            "#### 关键例子与反例（选读）",
                            "  - 用来检验理解的典型例子（不写成练习题）",
                            "  - 边界情况或反例：帮助界定概念的适用范围",
                            "#### 自检清单（选读）",
                            "  - 学完后应能回答的 5 个问题（可用作自我检测）",
                        ]
                    )

                template_lines: List[str] = []
                try:
                    sec_min = 6
                    sec_max = 9
                    if preset == "quick":
                        sec_min, sec_max = 5, 7
                    elif preset == "deep":
                        sec_min, sec_max = 8, 11
                    elif preset == "research":
                        sec_min, sec_max = 9, 13

                    outline_prompt = {
                        "topic": topic,
                        "subject": subject,
                        "knowledge_point": kp,
                        "preset": preset,
                        "ability_level": str(ctx.user_profile.ability_level or "unknown"),
                        "ability_score": float(ctx.user_profile.ability_score or 0.5),
                        "requirements": requirements,
                        "constraints": [
                            "请为该知识点设计一份『讲解结构提纲』，用于后续撰写。",
                            f"sections 数量建议：{sec_min}~{sec_max} 个（不必凑满，但要覆盖核心内容）。",
                            "只输出严格 JSON：{\"sections\":[{\"title\":\"...\",\"hints\":[\"...\",...]}, ...]}。",
                            "title 用中文短语，避免机械复用固定模板标题；要体现本知识点特点。",
                            "hints 每节 1~4 条，简短提示即可（用于指导写作）。",
                            "必须覆盖：定义/表述、直观理解、关键结论或性质/条件、常见误区、解题/应用框架或总结。",
                            "不要输出例题/练习题；不要输出 URL；不要输出 Markdown。",
                        ],
                    }
                    outline_raw = (
                        await self._call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的教学结构设计助手，只输出JSON。"},
                                {"role": "user", "content": json.dumps(outline_prompt, ensure_ascii=False)},
                            ],
                            model=writer_model,
                            temperature=0.2,
                            max_tokens=1200,
                            response_format={"type": "json_object"},
                        )
                    ).strip()
                    outline_obj = self._extract_json_obj(outline_raw)
                    outline_sections = outline_obj.get("sections") if isinstance(outline_obj, dict) else None
                    if isinstance(outline_sections, list):
                        for sec in outline_sections[: max(4, sec_max)]:
                            if not isinstance(sec, dict):
                                continue
                            title = str(sec.get("title") or "").strip().strip("# ")
                            if not title:
                                continue
                            if len(title) > 48:
                                title = title[:48].rstrip() + "…"
                            template_lines.append(f"#### {title}")
                            hints = sec.get("hints")
                            if isinstance(hints, list):
                                for h in hints[:4]:
                                    s = str(h or "").strip().replace("\n", " ").strip()
                                    if not s:
                                        continue
                                    if len(s) > 60:
                                        s = s[:60].rstrip() + "…"
                                    template_lines.append(f"  - {s}")
                except Exception:
                    template_lines = []

                if not template_lines:
                    template_lines = list(fallback_template_lines)

                length_note = ""
                if preset == "quick":
                    length_note = "篇幅：尽量精炼；每小节 3~6 条要点为主，避免长段落。"
                elif preset in {"deep", "research"}:
                    length_note = (
                        "篇幅：允许更详细；关键结论尽量 ≥ 5 条，误区 ≥ 3 条（若适用）。"
                        if preset == "deep"
                        else "篇幅：研究型；关键结论尽量 ≥ 6 条，误区 ≥ 3 条，补充推导骨架与自检清单。"
                    )

                extra_req = f"\n额外写作要求（来自用户）：{requirements}\n" if requirements else ""

                instructions = (
                    "【任务】为知识点生成一份可直接自学的讲解（Markdown），嵌入到「### 核心讲解」下方。\n"
                    "\n"
                    f"【生成预设】{preset}\n"
                    f"{length_note}\n"
                    f"{extra_req}"
                    "\n"
                    "【写作理念 — 费曼学习法】\n"
                    "1. 先讲「为什么」：概念要解决什么问题？没有它会怎样？\n"
                    "2. 类比先行：用日常生活或已学知识建立直觉，再给严格定义\n"
                    "3. 渐进深入：从最简单情形讲起，逐步添加复杂度\n"
                    "4. 重点突出：关键结论**加粗**，避免淹没在长段落中\n"
                    "5. 误区预警：主动指出初学者易错点，说明「为何会错」和「如何避免」\n"
                    "\n"
                    "【目标读者】自学者。根据 ability_score 调整深度：\n"
                    "  - 0.0~0.3：侧重直观、类比、生活例子，少用抽象符号\n"
                    "  - 0.4~0.6：直觉与严谨并重，给出完整定义但配合解释\n"
                    "  - 0.7~1.0：可更严谨抽象，补充推导细节和边界条件\n"
                    "\n"
                    "【结构提纲】（本知识点自适应；允许微调顺序，但需覆盖核心内容）\n"
                    + "\n".join(template_lines)
                    + "\n\n"
                    "【硬性格式要求】\n"
                    "- 小节标题从 `####` 开始，禁止输出 `#`/`##`/`###`\n"
                    '- 不输出"参考资料/外部链接"段落，不输出任何 URL\n'
                    "- 不输出 `[[1]]` 等证据标记，不写「根据网页/维基」等过程描述\n"
                    "- 数学公式：行内 $...$，独立行 $$...$$\n"
                    "\n"
                    "【内容质量要求】\n"
                    "- 原创综合：严禁照抄任何数据源（包括 MCP 工具返回的搜索摘要、网页正文、维基百科、StackExchange 等）的原文；\n"
                    "  所有来源仅作为「理解素材」，必须先完全消化，再用你自己的语言重新组织和表达\n"
                    "- 禁止搬运：不得将搜索结果、网页抓取内容或 API 返回的文本直接粘贴或仅做微小改动后输出；\n"
                    "  如果发现某段话与来源高度相似，必须彻底改写（换结构、换表述、换例子）\n"
                    "- 多源整合：综合多条来源的共同结论，不按来源逐条复述，不保留来源的行文结构\n"
                    "- 极短引用：如需引用原句，用引号标注且 ≤20 字，并立即用自己的话解释\n"
                    "- 信息不足时：明确标注「推断」或「建议」\n"
                    "- 不输出例题或练习题\n"
                )

                payload = {
                    "topic": topic,
                    "subject": subject,
                    "ability_level": str(ctx.user_profile.ability_level or "unknown"),
                    "ability_score": float(ctx.user_profile.ability_score or 0.5),
                    "knowledge_point": kp,
                    "wikipedia": {
                        "title": wiki.get("title"),
                        "url": wiki.get("url"),
                        "summary": wiki.get("summary"),
                    },
                    "mediawiki": {
                        "title": mw.get("title"),
                        "url": mw.get("url"),
                        "summary": mw.get("summary"),
                        "base_url": mw.get("base_url"),
                    },
                    "web_provider": web_provider,
                    "web_scope": web_scope,
                    "web_summary": web_summary,
                    "web_results": [
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "snippet": _clip_text(
                                str(r.get("snippet") or r.get("text") or ""),
                                900 if preset == "research" else 600,
                            ),
                        }
                        for r in web_results
                    ],
                    "web_pages": [
                        {
                            "title": p.get("title"),
                            "url": p.get("url"),
                            "extract": _clip_text(str(p.get("text") or ""), max_page_chars),
                        }
                        for p in web_pages
                    ],
                    "github_repos": [
                        {
                            "full_name": r.get("full_name"),
                            "url": r.get("url"),
                            "description": r.get("description"),
                            "stars": r.get("stars"),
                            "language": r.get("language"),
                            "readme_excerpt": _clip_text(str(r.get("readme_excerpt") or ""), max_page_chars),
                        }
                        for r in (gh.get("results") if isinstance(gh.get("results"), list) else [])[:10]
                        if isinstance(r, dict)
                    ],
                    "stackexchange": [
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "score": r.get("score"),
                            "tags": r.get("tags"),
                            "question_text": _clip_text(str(r.get("question_text") or ""), max_page_chars),
                            "top_answer_text": _clip_text(str(r.get("top_answer_text") or ""), max_page_chars),
                        }
                        for r in (se.get("results") if isinstance(se.get("results"), list) else [])[:8]
                        if isinstance(r, dict)
                    ],
                    "instructions": instructions,
                }
                cont_limit_raw = str(os.getenv("STUDY_MATERIALS_MAX_CONTINUATIONS") or "20").strip()
                try:
                    cont_limit = int(cont_limit_raw)
                except Exception:
                    cont_limit = 20
                cont_limit = max(0, min(cont_limit, 100))

                md_res = await self._call_llm_markdown_with_continuation(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是一位经验丰富的教育专家，擅长将复杂概念拆解为可自学的清晰讲解。\n"
                                "你遵循「费曼学习法」：如果不能用简单语言解释清楚，说明还没真正理解。\n"
                                "你的目标是让读者「恍然大悟」，而非堆砌信息。\n"
                                "输出必须是 Markdown。\n"
                                "【最高优先级规则】下方 JSON 中的 wikipedia/web_summary/web_results/web_pages/stackexchange 等字段\n"
                                "仅供你理解知识点，绝对禁止将其原文或近似原文搬入输出。你必须完全用自己的话重写。"
                            ),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    model=writer_model,
                    temperature=0.25,
                    max_tokens=writer_max_tokens,
                    reasoning=writer_reasoning,
                    continuation_context={"topic": topic, "subject": subject, "knowledge_point": kp, "preset": preset},
                    max_continuations=cont_limit,
                    raise_on_fail=strict_llm,
                )
                explanation_md = str(md_res.get("content") or "").strip()
                explanation_finish_reason = str(md_res.get("finish_reason") or "").strip()
                explanation_usage = md_res.get("usage") if isinstance(md_res.get("usage"), dict) else {}
                try:
                    explanation_continuations = int(md_res.get("continuations") or 0)
                except Exception:
                    explanation_continuations = 0

                if not explanation_md:
                    # Retry with a smaller payload to reduce context length / provider issues.
                    mini_payload = {
                        "topic": topic,
                        "subject": subject,
                        "ability_level": str(ctx.user_profile.ability_level or "unknown"),
                        "ability_score": float(ctx.user_profile.ability_score or 0.5),
                        "knowledge_point": kp,
                        "wikipedia_summary": _clip_text(str(wiki.get("summary") or ""), 800),
                        "mediawiki_summary": _clip_text(str(mw.get("summary") or ""), 800),
                        "web_summary": _clip_text(web_summary, 1400) if web_summary else "",
                        "web_results": [
                            {
                                "title": r.get("title"),
                                "url": r.get("url"),
                                "snippet": _clip_text(str(r.get("snippet") or r.get("text") or ""), 260),
                            }
                            for r in web_results[:5]
                        ],
                        "instructions": instructions,
                        "note": "上一次生成返回为空，请基于以上摘要重试生成讲解（仍需输出 Markdown）。",
                    }
                    mini_res = await self._call_llm_markdown_with_continuation(
                        messages=[
                            {
                                "role": "system",
                                "content": "你是严谨的自学资料编写老师。所有讲解必须为原创改写与综合，严禁直接搬运或拼贴 MCP/搜索/维基等数据源返回的原文；必须完全用自己的话重新组织。输出必须是 Markdown。",
                            },
                            {"role": "user", "content": json.dumps(mini_payload, ensure_ascii=False)},
                        ],
                        model=writer_model,
                        temperature=0.25,
                        max_tokens=writer_max_tokens,
                        reasoning=writer_reasoning,
                        continuation_context={"topic": topic, "subject": subject, "knowledge_point": kp, "preset": preset},
                        max_continuations=cont_limit,
                        raise_on_fail=strict_llm,
                    )
                    explanation_md = str(mini_res.get("content") or "").strip()
                    explanation_finish_reason = str(mini_res.get("finish_reason") or "").strip()
                    explanation_usage = mini_res.get("usage") if isinstance(mini_res.get("usage"), dict) else {}
                    try:
                        explanation_continuations = int(mini_res.get("continuations") or 0)
                    except Exception:
                        explanation_continuations = 0

                if explanation_md:
                    explanation_source = "llm"

            if not explanation_md:
                # If the main writer LLM isn't configured, optionally fall back to Metaso /ask as a "writer".
                # This keeps the pipeline AI-powered even when only METASO_API_KEY is available.
                if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                    fallback_raw = (os.getenv("STUDY_MATERIALS_METASO_WRITER_FALLBACK") or "1").strip().lower()
                    use_metaso_writer = fallback_raw in {"1", "true", "yes", "y", "on"}
                    if use_metaso_writer:
                        try:
                            from backend.mcp.metaso_search import metaso_ask as _metaso_ask

                            metaso_template_lines = [
                                "#### 1) 为什么需要它（动机与问题背景）",
                                "#### 2) 定义与核心表述",
                                "#### 3) 直观理解（类比与图像）",
                                "#### 4) 关键结论与性质",
                                "#### 5) 常见误区与易错点",
                                "#### 6) 解题/应用思路小结",
                            ]
                            if preset in {"deep", "research"}:
                                metaso_template_lines.extend(
                                    [
                                        "#### 7) 推导/证明思路",
                                        "#### 8) 联系与拓展（前置知识/相邻概念/典型应用）",
                                    ]
                                )
                            if preset == "research":
                                metaso_template_lines.extend(
                                    [
                                        "#### 9) 关键例子与反例",
                                        "#### 10) 自检清单（学完应能回答的 5 个问题）",
                                    ]
                                )

                            metaso_prompt_lines = [
                                f"请为知识点「{kp}」编写可直接自学的讲解（中文 Markdown）。",
                                "",
                                "【写作理念】费曼学习法：先讲为什么需要，再给定义；用类比建立直觉；重点加粗；主动指出误区。",
                                f"【生成预设】{preset}",
                                f"【额外要求】{requirements}" if requirements else "",
                                "",
                                "【硬性格式要求】",
                                "- 小节标题从 #### 开始，禁止 #/##/###",
                                "- 不输出参考资料/外部链接，不输出任何 URL",
                                "- 不输出 [[1]] 等证据标记，不写过程性叙述",
                                "- 严禁照抄 MCP/搜索/维基等数据源返回的原文，必须完全用自己的话重新组织和表达",
                                "- 数学公式：行内 $...$，独立行 $$...$$",
                                "- 不输出例题或练习题",
                                "",
                                "【模板结构】",
                                *metaso_template_lines,
                            ]
                            metaso_prompt = "\n".join([x for x in metaso_prompt_lines if str(x or "").strip()]).strip()

                            fmt = str(os.getenv("METASO_ASK_FORMAT") or "simple").strip() or "simple"
                            model_hint = str(os.getenv("METASO_ASK_MODEL") or "").strip()
                            metaso_res = await _metaso_ask(
                                query=metaso_prompt,
                                scope="webpage",
                                size=6,
                                format=fmt,
                                model=model_hint,
                            )
                            if (
                                isinstance(metaso_res, dict)
                                and metaso_res.get("success")
                                and str(metaso_res.get("answer") or "").strip()
                            ):
                                explanation_md = str(metaso_res.get("answer") or "").strip()
                                explanation_source = "metaso-ask-writer"
                        except Exception:
                            # Best-effort fallback only; never block the pipeline.
                            pass

                # If the main LLM isn't available or returned empty, prefer Metaso /ask summary notes
                # (already AI-generated) over a raw encyclopedia excerpt.
                if not explanation_md:
                    if strict_llm:
                        raise RuntimeError(f"llm_generation_failed: empty_explanation knowledge_point={kp}")
                    if web_summary:
                        explanation_md = web_summary.strip()
                        explanation_source = web_provider or "web_summary"
                    else:
                        wiki_summary = str(wiki.get("summary") or "").strip()
                        if wiki_summary:
                            explanation_md = f"**百科摘要**：{wiki_summary}\n"
                            explanation_source = "wikipedia"
                        else:
                            mw_summary = str(mw.get("summary") or "").strip()
                            if mw_summary:
                                explanation_md = f"**MediaWiki 摘要**：{mw_summary}\n"
                                explanation_source = "mediawiki"
                            else:
                                explanation_md = "（未获取到可靠百科摘要；以下内容以网络检索笔记为主，建议稍后重试生成。）\n"
                                explanation_source = "fallback"

            explanation_md = _sanitize_explanation_markdown(explanation_md, knowledge_point=kp)

            diagram: Dict[str, Any] = {}
            existing_diagrams: List[Dict[str, Any]] = []
            try:
                diagrams_blob = ctx.working_memory.get("diagrams")
                entries: List[Dict[str, Any]] = []
                if isinstance(diagrams_blob, dict):
                    if isinstance(diagrams_blob.get("items"), list):
                        entries = [x for x in (diagrams_blob.get("items") or []) if isinstance(x, dict)]
                    elif isinstance(diagrams_blob.get("sections"), list):
                        entries = [x for x in (diagrams_blob.get("sections") or []) if isinstance(x, dict)]
                for it in entries:
                    kp0 = str(it.get("knowledge_point") or "").strip()
                    if kp0 != kp:
                        continue
                    ds = it.get("diagrams")
                    if isinstance(ds, list):
                        existing_diagrams = [d for d in ds if isinstance(d, dict)]
                    break
            except Exception:
                existing_diagrams = []

            def _store_extra_diagram(diagram_obj: Dict[str, Any]) -> None:
                try:
                    blob = ctx.working_memory.get("diagrams")
                    if not isinstance(blob, dict):
                        blob = {}
                    items = blob.get("items")
                    if not isinstance(items, list):
                        items = []
                    kp_item: Optional[Dict[str, Any]] = None
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        if str(it.get("knowledge_point") or "").strip() == kp:
                            kp_item = it
                            break
                    if kp_item is None:
                        kp_item = {"knowledge_point": kp, "diagrams": []}
                        items.append(kp_item)
                    dlist = kp_item.get("diagrams")
                    if not isinstance(dlist, list):
                        dlist = []
                    filename = str(diagram_obj.get("filename") or "").strip()
                    if filename and any(
                        isinstance(d, dict) and str(d.get("filename") or "").strip() == filename for d in dlist
                    ):
                        return
                    dlist.append(diagram_obj)
                    kp_item["diagrams"] = [d for d in dlist if isinstance(d, dict)][-25:]
                    blob["items"] = [x for x in items if isinstance(x, dict)]
                    ctx.working_memory["diagrams"] = blob
                except Exception:
                    return

            need_diagrams = max(0, int(max_diagrams) - len(existing_diagrams))
            if with_diagrams and (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY) and need_diagrams > 0:
                try:
                    context_hints = {
                        "topic": topic,
                        "subject": subject,
                        "knowledge_point": kp,
                        "web_summary": _clip_text(web_summary, 1000) if web_summary else "",
                        "wikipedia_summary": _clip_text(str(wiki.get("summary") or ""), 600) if wiki.get("summary") else "",
                        "mediawiki_summary": _clip_text(str(mw.get("summary") or ""), 600) if mw.get("summary") else "",
                    }
                    prompt_lines = [
                        f"你是教学绘图助手。请为知识点「{kp}」生成最多 {need_diagrams} 张配图方案（JSON），用于帮助理解概念。",
                        "",
                        "只输出 JSON 对象，不要输出 Markdown、不要输出代码块。",
                        "",
                        "请输出严格 JSON：",
                        '{"diagrams":[{"kind":"plot_function|plot_3d|draw_diagram|svg_diagram","alt":"...","caption":"...","spec":{...}}, ...]}',
                        '若不需要画图请输出 {"diagrams":[]}。',
                        "",
                        "kind 说明：",
                        "- plot_function：二维函数图（输出 PNG；优先）。",
                        "- plot_3d：三维曲面图（输出 PNG）。",
                        "- draw_diagram：通用结构示意图/流程/关系图（输出 PNG）。",
                        "- svg_diagram：几何示意图（输出 SVG；只有 PNG 不方便表达时再用）。",
                        "",
                        "spec 示例（可参考，不必拘泥）：",
                        '1) plot_function：{"x_range":[-5,5],"y_range":[-2,2],"grid":true,"title":"...","curves":[{"expr":"sin(x)","label":"y=sin(x)"}]}',
                        '2) plot_3d：{"expr":"sin(x*y)","x_range":[-3,3],"y_range":[-3,3],"title":"..."}',
                        '3) draw_diagram：{"x_range":[-10,10],"y_range":[-6,6],"title":"...","objects":[{"id":"A","shape":"circle","pos":[-4,0],"r":0.35,"label":"A"}],"segments":[[[-4,0],[4,0]]],"annotations":[{"text":"...","x":0,"y":2}]}',
                        '4) svg_diagram：{"width":560,"height":320,"padding":24,"points":{"A":[80,240],"B":[440,240]},"segments":[["A","B"]],"labels":[{"point":"A","text":"A"}],"texts":[{"x":280,"y":30,"text":"...","anchor":"middle"}]}',
                        "",
                        "要求：",
                        f"1) 图必须和「{kp}」强相关，尽量简洁，能独立帮助理解。",
                        "2) 优先输出 PNG（plot_function/plot_3d/draw_diagram）；只有 PNG 不方便表达时才用 svg_diagram。",
                        "3) 不要画复杂背景或大段文字；caption 用一句中文即可。",
                        f"4) 数量不必凑满：0~{need_diagrams} 张均可。",
                        "",
                        "可参考信息（可能为空）：",
                        json.dumps(context_hints, ensure_ascii=False),
                    ]
                    prompt = "\n".join(prompt_lines)

                    raw = (
                        await self._call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的绘图规范生成器，只输出JSON。"},
                                {"role": "user", "content": prompt},
                            ],
                            model=writer_model,
                            temperature=0.2,
                            max_tokens=1800,
                            response_format={"type": "json_object"},
                        )
                    ).strip()

                    obj = self._extract_json_obj(raw)
                    diagrams_field = obj.get("diagrams") if isinstance(obj, dict) else None
                    items: List[Dict[str, Any]] = []
                    if isinstance(diagrams_field, list):
                        items = [x for x in (diagrams_field or []) if isinstance(x, dict)]
                    elif isinstance(obj, dict) and obj:
                        items = [obj]

                    for it in items[:need_diagrams]:
                        if not isinstance(it, dict):
                            continue
                        kind_raw = str(it.get("kind") or it.get("type") or "").strip().lower()
                        alt = str(it.get("alt") or "").strip() or f"{kp} 示意图"
                        caption = str(it.get("caption") or "").strip()

                        spec: Dict[str, Any] = it.get("spec") if isinstance(it.get("spec"), dict) else {}
                        if not spec:
                            spec = {
                                k: v
                                for k, v in it.items()
                                if k not in {"kind", "type", "alt", "caption"}
                            }
                        if not caption:
                            caption = str(spec.get("caption") or "").strip()

                        kind = kind_raw
                        if kind in {"plot", "plot2d", "plot_2d", "function", "function_plot", "plot_function"}:
                            kind = "plot_function"
                        elif kind in {"plot3d", "plot_3d", "surface", "surface_plot"}:
                            kind = "plot_3d"
                        elif kind in {"draw", "schematic", "diagram", "draw_diagram"}:
                            kind = "draw_diagram"
                        elif kind in {"svg", "svg_diagram", "draw_svg_diagram"}:
                            kind = "svg_diagram"
                        else:
                            kind = "svg_diagram"

                        d_obj: Optional[Dict[str, Any]] = None
                        if kind == "plot_function":
                            res = await self._tool_plot_function(
                                {
                                    "spec": spec,
                                    "alt": alt,
                                    "caption": caption,
                                    "knowledge_point": kp,
                                },
                                ctx,
                            )
                            if isinstance(res, dict) and res.get("success") and isinstance(res.get("diagram"), dict):
                                d_obj = dict(res.get("diagram") or {})
                        elif kind == "plot_3d":
                            res = await self._tool_plot_3d(
                                {
                                    "spec": spec,
                                    "alt": alt,
                                    "caption": caption,
                                    "knowledge_point": kp,
                                },
                                ctx,
                            )
                            if isinstance(res, dict) and res.get("success") and isinstance(res.get("diagram"), dict):
                                d_obj = dict(res.get("diagram") or {})
                        elif kind == "draw_diagram":
                            res = await self._tool_draw_diagram(
                                {
                                    "spec": spec,
                                    "alt": alt,
                                    "caption": caption,
                                    "knowledge_point": kp,
                                },
                                ctx,
                            )
                            if isinstance(res, dict) and res.get("success") and isinstance(res.get("diagram"), dict):
                                d_obj = dict(res.get("diagram") or {})
                        else:
                            draw_res = await self._tool_draw_svg_diagram({"spec": spec, "alt": alt}, ctx)
                            if isinstance(draw_res, dict) and draw_res.get("success"):
                                d_obj = {
                                    "knowledge_point": kp,
                                    "kind": "draw_svg_diagram",
                                    "url": str(draw_res.get("url") or "").strip(),
                                    "markdown": str(draw_res.get("markdown") or "").strip(),
                                    "filename": str(draw_res.get("filename") or "").strip(),
                                    "media_id": str(draw_res.get("media_id") or "").strip(),
                                    "caption": caption,
                                }

                        if not (isinstance(d_obj, dict) and str(d_obj.get("url") or "").strip()):
                            continue
                        if caption and not str(d_obj.get("caption") or "").strip():
                            d_obj["caption"] = caption
                        _store_extra_diagram(d_obj)
                        if not diagram:
                            diagram = {
                                "url": d_obj.get("url"),
                                "markdown": d_obj.get("markdown"),
                                "filename": d_obj.get("filename"),
                                "media_id": d_obj.get("media_id"),
                                "caption": d_obj.get("caption"),
                            }
                except Exception:
                    diagram = {}

            # Example solutions
            solved_examples: List[Dict[str, Any]] = []
            for ex in examples:
                stem = str(ex.get("stem") or "").strip()
                if not stem:
                    continue
                sol_md = ""
                if LESSON_PLAN_API_KEY or MOONSHOT_API_KEY:
                    prompt = (
                        "请为下面例题写出详细分步解答（Markdown）。\n\n"
                        "要求：\n- 每一步说明在做什么\n- 结论清晰\n\n"
                        f"题目：\n{stem}\n"
                    )
                    sol_md = (
                        await self._call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的解题老师，输出必须是Markdown。"},
                                {"role": "user", "content": prompt},
                            ],
                            model=writer_model,
                            temperature=0.3,
                            max_tokens=4000,
                            reasoning=writer_reasoning,
                        )
                    ).strip()
                if not sol_md:
                    sol_md = "（模型未配置或调用失败，无法生成解答。）"
                solved_examples.append(
                    {
                        "question_id": ex.get("question_id"),
                        "stem": stem,
                        "solution_markdown": sol_md,
                        "difficulty": ex.get("difficulty"),
                        "source": ex.get("source"),
                    }
                )

            # LLM fallback when the question bank returns nothing (avoid empty sections in the final archive).
            # Note: question generation is optional and disabled by default (concept-first).
            default_min_exercises = 2 if with_questions else 0
            try:
                min_exercises = int(args.get("min_exercises") or default_min_exercises)
            except Exception:
                min_exercises = default_min_exercises
            min_exercises = max(0, min(min_exercises, 5))

            have_exercise_stems = {
                str(e.get("stem") or "").strip()
                for e in exercises
                if isinstance(e, dict) and str(e.get("stem") or "").strip()
            }
            need_example = bool(with_questions and max_examples > 0 and not solved_examples)
            need_exercises = bool(with_questions and len(have_exercise_stems) < min_exercises)

            if (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY) and (need_example or need_exercises):
                example_count = 1 if need_example else 0
                exercise_count = (min_exercises - len(have_exercise_stems)) if need_exercises else 0
                exercise_count = max(0, min(exercise_count, 5))

                parts = [
                    f"请为知识点「{kp}」生成练习内容，并严格按 JSON 输出（不要 Markdown 代码块，不要额外解释文字）。",
                    "",
                    "需要生成：",
                    f"- 例题数量：{example_count}（例题需包含详细解答）",
                    f"- 练习题数量：{exercise_count}（只给题干，不要答案）",
                    "",
                    "JSON 格式必须是：",
                    "{",
                    '  "example": {"stem": "...", "solution_markdown": "..."},',
                    '  "exercises": [{"stem": "..."}, {"stem": "..."}]',
                    "}",
                    "",
                    "要求：",
                    "1) 题目必须与知识点强相关，避免过于宽泛。",
                    "2) 数学公式使用 LaTeX：行内用 $...$，独立行用 $$...$$。",
                    "3) solution_markdown 必须是 Markdown，包含分步推导与最后结论。",
                    "4) stem/solution_markdown 均不要包含外部链接。",
                    "5) 如果某项数量为 0，请返回对应为空对象/空数组（例如 example 可以为 {}，exercises 可以为 []）。",
                ]
                prompt = "\n".join(parts)

                raw = (
                    await self._call_llm_text(
                        messages=[
                            {
                                "role": "system",
                                "content": "你是严谨的数学出题与解题老师。你只输出严格 JSON，不输出任何额外文字。",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        model=writer_model,
                        temperature=0.3,
                        max_tokens=5000,
                        response_format={"type": "json_object"},
                    )
                ).strip()

                obj = self._extract_json_obj(raw)
                if need_example and isinstance(obj.get("example"), dict):
                    gen_ex = obj.get("example") or {}
                    stem = str(gen_ex.get("stem") or "").strip()
                    sol = str(gen_ex.get("solution_markdown") or "").strip()
                    if stem:
                        solved_examples.append(
                            {
                                "question_id": None,
                                "stem": stem,
                                "solution_markdown": sol or "（未生成到解答内容）",
                                "difficulty": None,
                                "source": "llm-generated",
                            }
                        )

                if need_exercises and isinstance(obj.get("exercises"), list):
                    for item in obj.get("exercises") or []:
                        stem = ""
                        if isinstance(item, dict):
                            stem = str(item.get("stem") or "").strip()
                        else:
                            stem = str(item or "").strip()
                        if not stem or stem in have_exercise_stems:
                            continue
                        exercises.append({"stem": stem, "source": "llm-generated"})
                        have_exercise_stems.add(stem)
                        if len(have_exercise_stems) >= min_exercises:
                            break

            sections.append(
                {
                    "knowledge_point": kp,
                    "explanation_markdown": explanation_md,
                    "explanation_source": explanation_source,
                    "explanation_finish_reason": explanation_finish_reason,
                    "explanation_usage": explanation_usage,
                    "explanation_continuations": explanation_continuations,
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
                    "examples": solved_examples,
                    "exercises": exercises,
                }
            )

        # Note: per-knowledge-point runs are merged by ContextManager.on_step_result (by knowledge_point),
        # so we only return the sections generated in *this* call.
        return {
            "topic": topic,
            "subject": subject,
            "preset": preset,
            "requirements": requirements,
            "sections": sections,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
