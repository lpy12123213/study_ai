"""Default step specifications shared by ``Planner._fallback_plan`` and ``Planner._parse_llm_plan``.

Pure data: each entry maps a tool name to the canonical title / arguments /
foreach / parallel-group used by both the deterministic fallback planner and
the LLM-plan validator. Keeping the spec map here means any tweak to e.g. the
``synthesize_sources`` cap propagates to both code paths automatically.

The function lives on its own so the (already long) ``planner.py`` module
focuses on the planning algorithm itself rather than per-tool defaults.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = ["default_step_spec"]


def default_step_spec(
    tool: str,
    *,
    topic: str,
    subject: str,
    difficulty: str,  # noqa: ARG001 – kept for API parity with the original planner method
    preset: str,
    requirements: str,
    max_web_pages: int,
    enable_diagrams: bool,
    enable_questions: bool,
    issues: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Return the canonical step descriptor for ``tool`` or ``None`` when the
    tool is not part of the standard study-material pipeline.
    """

    t = str(tool or "").strip()
    if not t:
        return None

    if t == "aggregate_knowledge":
        return {
            "title": "聚合多源资料（按知识点）",
            "arguments": {"topic": topic, "subject": subject},
            "foreach_knowledge_point": True,
            "parallel_group": "",
            "thought": "把网搜/题库结果按知识点聚合，形成可用于写作的统一素材。",
        }

    if t == "synthesize_sources":
        max_web_results = 10 if preset == "quick" else 12 if preset == "standard" else 14
        return {
            "title": "综合源简报（按知识点）",
            "arguments": {
                "topic": topic,
                "subject": subject,
                "max_web_results": max_web_results,
                "max_web_pages": max_web_pages,
                "max_page_chars": 2600 if preset != "research" else 3200,
            },
            "foreach_knowledge_point": True,
            "parallel_group": "kp_prewrite",
            "thought": "对聚合素材去噪并提炼关键事实，生成结构化源简报，降低后续写作噪声与上下文长度。",
        }

    if t == "detect_knowledge_type":
        return {
            "title": "检测知识类型（按知识点）",
            "arguments": {"topic": topic, "subject": subject},
            "foreach_knowledge_point": True,
            "parallel_group": "kp_prewrite",
            "thought": "判断知识点类型（定义/定理/算法等），为后续自适应大纲与写作提供结构先验。",
        }

    if t == "generate_outline":
        return {
            "title": "生成自适应大纲（按知识点）",
            "arguments": {"topic": topic, "subject": subject, "preset": preset, "requirements": requirements},
            "foreach_knowledge_point": True,
            "parallel_group": "",
            "thought": "基于知识类型与源简报生成写作大纲（含验证标准），为分段并行写作做准备。",
        }

    if t == "generate_study_material":
        max_web_results = 15 if preset == "research" else 12 if preset == "deep" else 10
        return {
            "title": "生成概念讲解（按知识点）",
            "arguments": {
                "topic": topic,
                "subject": subject,
                "preset": preset,
                "requirements": requirements,
                "max_examples": 1 if enable_questions else 0,
                "max_points": 1,
                "max_web_results": max_web_results,
                "max_web_pages": max_web_pages,
                "max_page_chars": 3200 if preset == "research" else 2600,
                "with_questions": bool(enable_questions),
                # Diagrams are generated in a separate stage (generate_diagrams).
                "with_diagrams": False,
            },
            "foreach_knowledge_point": True,
            "parallel_group": "",
            "thought": "按大纲对当前知识点进行分段并行写作，生成可直接自学的核心讲解草稿（配图在后续阶段生成）。",
        }

    if t == "critique_draft":
        return {
            "title": "自我批判（按知识点）",
            "arguments": {"topic": topic, "subject": subject},
            "foreach_knowledge_point": True,
            "parallel_group": "kp_postwrite",
            "thought": "对草稿多维度审查（结构/准确性/完整性/原创性/深度匹配），给出可执行修订指令。",
        }

    if t == "generate_diagrams":
        if not enable_diagrams:
            return None
        return {
            "title": "生成教学配图（按知识点）",
            "arguments": {"topic": topic, "subject": subject, "preset": preset},
            "foreach_knowledge_point": True,
            "parallel_group": "kp_postwrite",
            "thought": "为该知识点生成必要的示意图（与自我批判并行），帮助直观理解。",
        }

    if t == "refine_draft":
        return {
            "title": "精炼修订（按知识点）",
            "arguments": {"topic": topic, "subject": subject},
            "foreach_knowledge_point": True,
            "parallel_group": "",
            "thought": "根据批判意见对草稿做定向修订（高分则自动跳过）。",
        }

    if t == "assemble_study_archive":
        return {
            "title": "组装自学档案 Markdown",
            "arguments": {"topic": topic, "subject": subject},
            "foreach_knowledge_point": False,
            "parallel_group": "",
            "thought": "将生成内容整理成结构化 Markdown：讲解（含示意图）→ 资料来源。",
        }

    if t == "revise_markdown":
        issues = issues or []
        return {
            "title": "根据审查问题修订 Markdown",
            "arguments": {"issues": issues},
            "foreach_knowledge_point": False,
            "parallel_group": "",
            "thought": "根据自检发现的问题修订内容，提升完整性与可读性。",
        }

    if t == "save_markdown_file":
        return {
            "title": "保存 Markdown 到文件",
            "arguments": {"topic": topic, "dir": "study_archives"},
            "foreach_knowledge_point": False,
            "parallel_group": "",
            "thought": "把最终结果保存为本地 Markdown 文件，便于复习与分享。",
        }

    if t == "export_study_markdown":
        return {
            "title": "导出 Markdown 下载文件",
            "arguments": {"topic": topic},
            "foreach_knowledge_point": False,
            "parallel_group": "",
            "thought": "将最终 Markdown 发布为可下载链接，前端仅展示下载入口而不直接渲染全文。",
        }

    if t == "convert_markdown_to_latex":
        return {
            "title": "Markdown → LaTeX（ElegantBook）",
            "arguments": {"topic": topic, "subject": subject},
            "foreach_knowledge_point": False,
            "parallel_group": "",
            "thought": "使用 LLM 将 Markdown 转为 ElegantBook LaTeX，为编译 PDF 做准备。",
        }

    if t == "refine_latex":
        return {
            "title": "LaTeX 二次修订",
            "arguments": {"topic": topic, "subject": subject},
            "foreach_knowledge_point": False,
            "parallel_group": "",
            "thought": "对 LaTeX 进行二次修订，尽量减少编译失败与排版问题。",
        }

    if t == "compile_latex_to_pdf":
        return {
            "title": "编译 PDF",
            "arguments": {"topic": topic},
            "foreach_knowledge_point": False,
            "parallel_group": "",
            "thought": "编译 LaTeX 生成 PDF，并发布为可下载链接。",
        }

    if t == "review_content":
        return {
            "title": "内容审查",
            "arguments": {"topic": topic, "subject": subject},
            "foreach_knowledge_point": False,
            "parallel_group": "",
            "thought": "对结构、准确性与可读性做最后自检，避免明显错误与空泛表述。",
        }

    return None
