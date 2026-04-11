from __future__ import annotations

from typing import Dict, Optional

from backend.agent.mcp.registry import MCPToolRegistry


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
    "generate_diagrams": "生成配图：为知识点规划并渲染教学示意图（TikZ/Asymptote；必要时 Seedream），结果写入 diagrams",
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
    "asy_to_svg": "使用 Asymptote 编译生成 SVG 矢量图（静态技术图备选）",
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


def build_allowed_tools(
    *,
    enable_questions: bool,
    enable_extra_tools: bool,
    enable_diagrams: bool,
    tool_registry: Optional[MCPToolRegistry] = None,
) -> Dict[str, str]:
    if tool_registry is None:
        tools: Dict[str, str] = dict(_CORE_TOOLS)
        if enable_diagrams:
            tools.update(_DRAW_TOOLS)
        if enable_questions:
            tools.update(_QUESTION_TOOLS)
        if enable_extra_tools:
            tools.update(_EXTRA_TOOLS)
        return tools

    optional_diagram_tools = set(_DRAW_TOOLS.keys())
    optional_question_tools = set(_QUESTION_TOOLS.keys())
    optional_extra_tools = set(_EXTRA_TOOLS.keys())

    tools: Dict[str, str] = {}
    for tool in tool_registry.list_tools():
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        if not enable_diagrams and name in optional_diagram_tools:
            continue
        if not enable_questions and name in optional_question_tools:
            continue
        if not enable_extra_tools and name in optional_extra_tools:
            continue
        desc = str(tool.get("description") or "").strip() or name
        tools[name] = desc
    return tools
