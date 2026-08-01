"""Static skill catalog for the agent tools skills-ification.

A skill is a named group of tools (name + one-liner + domain + prompt_id).
The ReAct loop exposes only the loaded skills' tools to the controller LLM and
lets the model expand the tool surface on demand via the `load_skill` inline
action. This module is pure data + pure helpers (no LLM or execution side
effects), so it stays safe to import from tests and from prompt assembly.

The catalog MUST stay in sync with the real MCP tool registry. The drift test
`backend/tests/test_skill_catalog.py` enforces `set(union of skill tools) ==
set(registry.list_tools())`, so adding a new tool without registering it in a
skill turns the test red.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.agent.mcp.registry import MCPToolRegistry

# ---------------------------------------------------------------------------
# Legacy flag semantics (preserved from backend/agent/planning/tool_catalog.py).
#
# - enable_questions gates `search_questions_by_knowledge` (examples skill).
# - enable_extra_tools gates the research extras
#   (wikipedia/mediawiki/stackexchange/github/browse_web_pages).
# - enable_diagrams gates the `diagrams` skill. To avoid a regression, the five
#   "always-on" diagram tools below were injected in legacy builds regardless of
#   enable_diagrams, so tools_for_skills() keeps injecting them unconditionally.
# ---------------------------------------------------------------------------

ALWAYS_ON_DIAGRAM_TOOLS: tuple[str, ...] = (
    "generate_diagrams",
    "draw_svg_diagram",
    "draw_diagram",
    "plot_function",
    "plot_3d",
)

# Gated by enable_diagrams (excluded when the flag is off, unless the diagrams
# skill is not loaded at all - in which case they are not injected anyway).
GATED_DIAGRAM_TOOLS: tuple[str, ...] = (
    "tikz_to_svg",
    "asy_to_svg",
    "render_chemistry",
    "render_circuit",
    "render_graphviz",
    "seedream_generate",
)

# Gated by enable_extra_tools (research skill extras).
RESEARCH_EXTRA_TOOLS: tuple[str, ...] = (
    "wikipedia_search",
    "mediawiki_search",
    "stackexchange_search",
    "github_search",
    "browse_web_pages",
)

# Gated by enable_questions (examples skill question tool).
QUESTION_TOOL = "search_questions_by_knowledge"

# Skills always available in a study-materials run (diagrams is appended when
# enable_diagrams). Compose skills are only available in compose runs.
STUDY_DOMAIN_SKILLS: tuple[str, ...] = ("planning", "research", "examples", "writing", "export")
COMPOSE_DOMAIN_SKILLS: tuple[str, ...] = ("paper-compose", "compose-sandbox")

SKILLS: Dict[str, Dict[str, Any]] = {
    "planning": {
        "name": "planning",
        "one_liner": "拆知识点、定类型、出大纲",
        "domain": "study",
        "tools": ["split_knowledge_points", "review_knowledge_points", "detect_knowledge_type", "generate_outline"],
        "prompt_id": "agent.skills.planning.v1",
    },
    "research": {
        "name": "research",
        "one_liner": "联网/百科/社区检索与聚合降噪",
        "domain": "study",
        "tools": [
            "web_search_knowledge",
            "browse_web_pages",
            "wikipedia_search",
            "mediawiki_search",
            "github_search",
            "stackexchange_search",
            "aggregate_knowledge",
            "synthesize_sources",
        ],
        "prompt_id": "agent.skills.research.v1",
    },
    "examples": {
        "name": "examples",
        "one_liner": "知识库与题库例题/练习检索",
        "domain": "study",
        "tools": ["retrieve_knowledge", "search_examples", "search_exercises", "search_questions_by_knowledge"],
        "prompt_id": "agent.skills.examples.v1",
    },
    "writing": {
        "name": "writing",
        "one_liner": "写作、审修、汇编、导出 markdown",
        "domain": "study",
        "tools": [
            "generate_study_material",
            "critique_draft",
            "refine_draft",
            "revise_markdown",
            "assemble_study_archive",
            "save_markdown_file",
            "export_study_markdown",
            "review_content",
        ],
        "prompt_id": "agent.skills.writing.v1",
    },
    "export": {
        "name": "export",
        "one_liner": "LaTeX/PDF 导出",
        "domain": "study",
        "tools": ["convert_markdown_to_latex", "refine_latex", "compile_latex_to_pdf"],
        "prompt_id": "agent.skills.export.v1",
    },
    "diagrams": {
        "name": "diagrams",
        "one_liner": "示意图/函数图像渲染",
        "domain": "study",
        "tools": [
            "generate_diagrams",
            "draw_svg_diagram",
            "draw_diagram",
            "tikz_to_svg",
            "asy_to_svg",
            "render_chemistry",
            "render_circuit",
            "render_graphviz",
            "seedream_generate",
            "plot_function",
            "plot_3d",
        ],
        "prompt_id": "agent.skills.diagrams.v1",
    },
    "paper-compose": {
        "name": "paper-compose",
        "one_liner": "题库组卷全流程",
        "domain": "compose",
        "tools": [
            "get_available_filters",
            "search_questions",
            "batch_get_question_details",
            "compose_paper_blueprint",
            "review_question_match",
            "create_paper",
            "analyze_paper",
            "crawl_questions_from_bank",
            "generate_questions_ai",
            "solve_question_independently",
            "render_paper_latex",
            "compile_latex_sandbox",
            "repair_latex",
        ],
        "prompt_id": "agent.skills.paper-compose.v1",
    },
    "compose-sandbox": {
        "name": "compose-sandbox",
        "one_liner": "组卷沙箱文件/执行",
        "domain": "compose",
        "tools": [
            "compose_sandbox_open",
            "compose_sandbox_write_file",
            "compose_sandbox_read_file",
            "compose_sandbox_run",
            "compose_sandbox_patch_question",
            "compose_sandbox_export",
            "compose_sandbox_close",
        ],
        "prompt_id": "agent.skills.compose-sandbox.v1",
    },
}

# The diagrams skill is available in both domains; it is appended by
# skills_for_domain() when enable_diagrams is true.
DIAGRAM_SKILL = "diagrams"


def skills_for_domain(
    domain: str,
    *,
    enable_diagrams: bool = True,
    enable_questions: bool = False,
    enable_extra_tools: bool = True,
) -> List[str]:
    """Return the skill names available for a run domain.

    - study: planning/research/examples/writing/export (+ diagrams if enabled).
    - compose: paper-compose/compose-sandbox (+ diagrams if enabled).

    `enable_questions` and `enable_extra_tools` do not change skill
    availability: they gate individual tools inside `tools_for_skills()`
    (search_questions_by_knowledge and the research extras respectively), which
    preserves the legacy flag semantics from `build_allowed_tools`.
    """
    d = str(domain or "").strip().lower()
    if d == "compose":
        names = list(COMPOSE_DOMAIN_SKILLS)
    else:
        names = list(STUDY_DOMAIN_SKILLS)
    if enable_diagrams:
        names.append(DIAGRAM_SKILL)
    return names


def normalize_active_skills(value: Any) -> List[str]:
    """Normalize a working_memory['active_skills'] value.

    A missing/non-list/empty value resets to the bootstrap skill list
    (["planning"]) so a fresh run never starts with an empty tool surface.
    Entries are stripped and deduplicated, order-preserving. Shared by the
    ReAct loop and prompt assembly so both see the same active skill set.
    """
    if not isinstance(value, list):
        return ["planning"]
    out: List[str] = []
    seen: set[str] = set()
    for raw in value:
        name = str(raw or "").strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out or ["planning"]


def find_skill_for_tool(name: str) -> Optional[str]:
    """Reverse lookup: which skill owns `name`, or None when unknown."""
    target = str(name or "").strip()
    if not target:
        return None
    for skill_name, skill in SKILLS.items():
        if target in skill["tools"]:
            return skill_name
    return None


def _tool_def_to_dict(tool: Any) -> Dict[str, Any]:
    if isinstance(tool, dict):
        return dict(tool)
    to_dict = getattr(tool, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    return {
        "name": str(getattr(tool, "name", "") or "").strip(),
        "description": str(getattr(tool, "description", "") or "").strip(),
        "input_schema": dict(getattr(tool, "input_schema", None) or {}),
    }


def tools_for_skills(
    active_skills: List[str],
    registry: MCPToolRegistry,
    *,
    enable_diagrams: bool = True,
    enable_questions: bool = False,
    enable_extra_tools: bool = True,
) -> List[Dict[str, Any]]:
    """Union of registry tool dicts for the active skills, honoring the flags.

    Legacy-preservation: the five `ALWAYS_ON_DIAGRAM_TOOLS`
    (generate_diagrams/draw_svg_diagram/draw_diagram/plot_function/plot_3d) were
    always injected regardless of enable_diagrams, so they are added even when
    the diagrams skill is not loaded or the flag is off. The other six diagram
    tools stay gated by enable_diagrams.

    Unknown skill names and unknown tool names are dropped silently (registry
    is the source of truth). Returns `MCPToolRegistry.list_tools()`-shaped dicts.
    """
    selected: List[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        n = str(name or "").strip()
        if n and n not in seen:
            seen.add(n)
            selected.append(n)

    for skill_name in active_skills or []:
        skill = SKILLS.get(str(skill_name or "").strip())
        if not skill:
            continue
        for tool in skill["tools"]:
            _add(tool)

    if not enable_diagrams:
        for name in GATED_DIAGRAM_TOOLS:
            seen.discard(name)
    if not enable_questions:
        seen.discard(QUESTION_TOOL)
    if not enable_extra_tools:
        for name in RESEARCH_EXTRA_TOOLS:
            seen.discard(name)

    # Legacy always-on diagram tools regardless of enable_diagrams.
    for name in ALWAYS_ON_DIAGRAM_TOOLS:
        _add(name)

    tools: List[Dict[str, Any]] = []
    for name in selected:
        if name not in seen:
            continue
        definition = registry.get_tool(name)
        if definition is None:
            continue
        tools.append(_tool_def_to_dict(definition))
    return tools
