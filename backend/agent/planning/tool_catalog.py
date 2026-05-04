from __future__ import annotations

from typing import Dict, Optional

from backend.agent.mcp.registry import MCPToolRegistry

_CORE_TOOLS: Dict[str, str] = {
    "split_knowledge_points": "Split the topic into searchable sub-knowledge points; outputs knowledge_points.",
    "review_knowledge_points": "Review and minimally adjust knowledge points for deduplication, coverage, and granularity.",
    "web_search_knowledge": "Search the web for a knowledge point; Exa first, optional deepresearch passes for deep/research, Metaso/Zhipu fallback. Returns results and optional summary.",
    "aggregate_knowledge": "Aggregate split points, web search, and optional question-bank/wiki/page/Q&A/GitHub sources.",
    "synthesize_sources": "Denoise aggregated material into writer-ready source_brief entries; writes source_briefs.",
    "detect_knowledge_type": "Detect knowledge type such as definition/theorem/algorithm; writes knowledge_types.",
    "generate_outline": "Generate an adaptive outline from knowledge_type and source_brief; writes outlines.",
    "generate_study_material": "Generate concept explanations from source_brief and outline; supports section-level parallel writing.",
    "critique_draft": "Critique drafts across dimensions and produce targeted revision instructions; writes critiques.",
    "refine_draft": "Apply targeted minimal revisions from critiques; high-scoring drafts may be skipped.",
    "generate_diagrams": "Plan and render instructional diagrams with TikZ/Asymptote and Seedream when needed; writes diagrams.",
    "assemble_study_archive": "Assemble the final self-study Markdown archive.",
    "revise_markdown": "Revise Markdown according to review issues when needed.",
    "save_markdown_file": "Save Markdown to a file.",
    "export_study_markdown": "Publish final Markdown as a downloadable file and return md_url.",
    "convert_markdown_to_latex": "Convert Markdown to ElegantBook LaTeX with an LLM and return tex_url.",
    "refine_latex": "Minimally refine LaTeX for structure, formulas, images, and compilation friendliness.",
    "compile_latex_to_pdf": "Compile LaTeX into PDF and return pdf_url.",
    "review_content": "Review content structure, completeness, and reliability.",
}

_DRAW_TOOLS: Dict[str, str] = {
    "tikz_to_svg": "Compile LaTeX TikZ into an SVG vector diagram.",
    "asy_to_svg": "Compile Asymptote into an SVG vector diagram; fallback for static technical diagrams.",
    "seedream_generate": "Generate images from natural language with Volcano Cloud Seedream 4.5 ARK images/generations.",
}

_QUESTION_TOOLS: Dict[str, str] = {
    "search_questions_by_knowledge": "Search the question bank by knowledge point for examples and exercises; disabled by default, enable with STUDY_MATERIALS_ENABLE_QUESTIONS=1.",
}

_EXTRA_TOOLS: Dict[str, str] = {
    "wikipedia_search": "Search Wikipedia; use the best language for the topic/user request.",
    "mediawiki_search": "Search MediaWiki sources such as Wikipedia, Wikibooks, or ProofWiki.",
    "stackexchange_search": "Search StackExchange for high-quality explanations and typical questions.",
    "github_search": "Search GitHub repositories for notes, tutorials, and code examples.",
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
