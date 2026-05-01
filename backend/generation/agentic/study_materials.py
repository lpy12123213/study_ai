from __future__ import annotations

from typing import Any, Dict, Optional

from backend.generation.agentic.types import (
    AgentBudget,
    AgentRoleSpec,
    AgentRunSpec,
    AgentSearchPolicy,
    AgentToolPolicy,
)


def _preset_budget(preset: str) -> AgentBudget:
    p = str(preset or "").strip().lower()
    if p == "quick":
        return AgentBudget(max_llm_calls=10, max_tool_calls=18, max_iterations=8, max_runtime_s=420)
    if p == "deep":
        return AgentBudget(max_llm_calls=24, max_tool_calls=42, max_iterations=18, max_runtime_s=1200)
    if p == "research":
        return AgentBudget(max_llm_calls=32, max_tool_calls=60, max_iterations=24, max_runtime_s=1800)
    return AgentBudget(max_llm_calls=18, max_tool_calls=32, max_iterations=14, max_runtime_s=900)


def build_study_materials_agent_spec(
    *,
    query: str,
    subject: str = "",
    options: Optional[Dict[str, Any]] = None,
    resume_state: Optional[Dict[str, Any]] = None,
) -> AgentRunSpec:
    opts = dict(options or {})
    topic = str(query or "").strip()
    subj = str(subject or "").strip()
    preset = str(opts.get("preset") or "standard").strip().lower() or "standard"
    requirements = str(opts.get("requirements") or "").strip()

    allowed_tools = [
        "split_knowledge_points",
        "review_knowledge_points",
        "web_search_knowledge",
        "wikipedia_search",
        "mediawiki_search",
        "browse_web_pages",
        "aggregate_knowledge",
        "synthesize_sources",
        "detect_knowledge_type",
        "generate_outline",
        "generate_study_material",
        "critique_draft",
        "generate_diagrams",
        "refine_draft",
        "assemble_study_archive",
        "review_content",
        "revise_markdown",
        "save_markdown_file",
        "export_study_markdown",
        "convert_markdown_to_latex",
        "refine_latex",
        "compile_latex_to_pdf",
    ]
    if bool(opts.get("with_questions")) or bool(opts.get("enable_questions")):
        allowed_tools.append("search_questions_by_knowledge")
    if bool(opts.get("enable_extra_tools")):
        allowed_tools.extend(["stackexchange_search", "github_search"])

    return AgentRunSpec(
        domain="study_materials",
        goal=f"生成可自学的学习资料：{topic}",
        subject=subj,
        user_requirements=requirements,
        input_payload={
            "topic": topic,
            "subject": subj,
            "preset": preset,
            "options": opts,
        },
        roles=[
            AgentRoleSpec(name="planner", prompt_id="agent.planner.study_materials.v1"),
            AgentRoleSpec(name="researcher", prompt_id="search.query.decompose.v1", required=False),
            AgentRoleSpec(name="writer", prompt_id="study.material.writer.v1"),
            AgentRoleSpec(name="reviewer", prompt_id="study.material.document_review.v1"),
            AgentRoleSpec(name="exporter", prompt_id="agent.exporter.study_materials.v1", required=False),
        ],
        tool_policy=AgentToolPolicy(
            allowed_tools=allowed_tools,
            allow_parallel=True,
            max_consecutive_failures=3,
            metadata={"preset": preset},
        ),
        search_policy=AgentSearchPolicy(providers=["tavily", "exa", "metaso", "bigmodel"]),
        budget=_preset_budget(preset),
        output_contract={"kind": "study_archive", "formats": ["markdown", "latex", "pdf"]},
        resume_state=dict(resume_state or {}),
        metadata={"adapter": "backend.agent.AgentCore", "migration_phase": "spec_sidecar"},
    )
