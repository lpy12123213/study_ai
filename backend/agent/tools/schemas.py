from __future__ import annotations

from typing import Any, Dict

# Centralized tool input schemas.
#
# Notes:
# - These are intentionally conservative and allow additional properties so the
#   agent can evolve without breaking old prompts.
# - Schema validation/coercion happens in `backend.agent.tools.utils.schema_validation`.


def _obj(properties: Dict[str, Any], *, required: list[str] | None = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
        "additionalProperties": True,
    }
    if required:
        schema["required"] = list(required)
    return schema


TOOL_INPUT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    # knowledge points
    "split_knowledge_points": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "min_points": {"type": "integer", "minimum": 1, "maximum": 10},
            "max_points": {"type": "integer", "minimum": 1, "maximum": 15},
        }
    ),
    "review_knowledge_points": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "min_points": {"type": "integer", "minimum": 1, "maximum": 10},
            "max_points": {"type": "integer", "minimum": 1, "maximum": 15},
        }
    ),

    # knowledge type detection
    "detect_knowledge_type": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "strict_llm": {"type": "boolean"},
        }
    ),

    # question bank
    "search_questions_by_knowledge": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "difficulty": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "examples_limit": {"type": "integer", "minimum": 0, "maximum": 3},
            "exercises_limit": {"type": "integer", "minimum": 0, "maximum": 10},
            "max_pages": {"type": "integer", "minimum": 1, "maximum": 3},
            "limit": {"type": "integer", "minimum": 10, "maximum": 60},
        }
    ),
    "retrieve_knowledge": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "difficulty": {"type": "string"},
        }
    ),
    "search_examples": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "difficulty": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
        }
    ),
    "search_exercises": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "difficulty": {"type": "string"},
            "limit": {"type": "integer", "minimum": 5, "maximum": 30},
        }
    ),

    # aggregation + synthesis
    "aggregate_knowledge": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
        }
    ),
    "synthesize_sources": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "strict_llm": {"type": "boolean"},
        }
    ),

    # search tools
    "web_search_knowledge": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            "query_hint": {"type": "string"},
            "scope": {"type": "string"},
            "include_summary": {"type": "boolean"},
            "text_max_length": {"type": "integer", "minimum": 200, "maximum": 8000},
            "preset": {"type": "string"},
            "search_mode": {"type": "string"},
            "decompose": {"type": "boolean"},
            "sub_questions": {"type": "integer", "minimum": 2, "maximum": 25},
            "disable_metaso": {"type": "boolean"},
            "metaso_mode": {"type": "string"},
            "strict_llm": {"type": "boolean"},
        }
    ),
    "browse_web_pages": _obj(
        {
            "knowledge_point": {"type": "string"},
            "urls": {"type": "array", "items": {"type": "string"}},
            "max_pages": {"type": "integer", "minimum": 1, "maximum": 8},
            "max_chars": {"type": "integer", "minimum": 500, "maximum": 12000},
            "timeout_s": {"type": "number", "minimum": 1, "maximum": 60},
        }
    ),
    "wikipedia_search": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "lang": {"type": "string"},
            "sentences": {"type": "integer", "minimum": 1, "maximum": 10},
            "max_content_length": {"type": "integer", "minimum": 200, "maximum": 8000},
            "concurrency": {"type": "integer", "minimum": 1, "maximum": 5},
        }
    ),
    "mediawiki_search": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "lang": {"type": "string"},
            "sentences": {"type": "integer", "minimum": 1, "maximum": 10},
            "max_content_length": {"type": "integer", "minimum": 200, "maximum": 8000},
            "concurrency": {"type": "integer", "minimum": 1, "maximum": 5},
        }
    ),
    "github_search": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        }
    ),
    "stackexchange_search": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "site": {"type": "string"},
            "tagged": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        }
    ),

    # generation core
    "generate_outline": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "preset": {"type": "string"},
            "requirements": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "strict_llm": {"type": "boolean"},
        }
    ),
    "generate_study_material": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "preset": {"type": "string"},
            "requirements": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object"}},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "max_points": {"type": "integer", "minimum": 1, "maximum": 15},
            "max_web_results": {"type": "integer", "minimum": 3, "maximum": 25},
            "max_web_pages": {"type": "integer", "minimum": 0, "maximum": 8},
            "max_page_chars": {"type": "integer", "minimum": 500, "maximum": 8000},
            "with_questions": {"type": "boolean"},
            "section_concurrency": {"type": "integer", "minimum": 1, "maximum": 6},
            "strict_llm": {"type": "boolean"},
        }
    ),
    "assemble_study_archive": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "preset": {"type": "string"},
            "requirements": {"type": "string"},
            "with_diagrams": {"type": "boolean"},
        }
    ),
    "save_markdown_file": _obj(
        {
            "path": {"type": "string"},
            "filename": {"type": "string"},
            "markdown": {"type": "string"},
            "user_id": {"type": "string"},
        }
    ),
    "export_study_markdown": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "path": {"type": "string"},
            "export_format": {"type": "string"},
        }
    ),

    # refinement / critique / review
    "critique_draft": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "strict_llm": {"type": "boolean"},
        }
    ),
    "refine_draft": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "threshold": {"type": "number", "minimum": 0, "maximum": 10},
            "preset": {"type": "string"},
            "strict_llm": {"type": "boolean"},
        }
    ),
    "review_content": _obj(
        {
            "topic": {"type": "string"},
            "strict_llm": {"type": "boolean"},
        }
    ),
    "revise_markdown": _obj(
        {
            "issues": {"type": "array", "items": {"type": "string"}},
        }
    ),

    # latex pipeline
    "convert_markdown_to_latex": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "markdown": {"type": "string"},
            "strict_llm": {"type": "boolean"},
        }
    ),
    "refine_latex": _obj(
        {
            "latex_tex": {"type": "string"},
            "strict_llm": {"type": "boolean"},
        }
    ),
    "compile_latex_to_pdf": _obj(
        {
            "latex_tex": {"type": "string"},
            "timeout_s": {"type": "number", "minimum": 5, "maximum": 3600},
        }
    ),

    # diagrams
    "generate_diagrams": _obj(
        {
            "topic": {"type": "string"},
            "subject": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "preset": {"type": "string"},
            "max_diagrams": {"type": "integer", "minimum": 0, "maximum": 12},
            "strict_llm": {"type": "boolean"},
        }
    ),
    "draw_svg_diagram": _obj(
        {
            "spec": {"type": "object"},
            "alt": {"type": "string"},
            "title": {"type": "string"},
        }
    ),
    "draw_diagram": _obj(
        {
            "knowledge_point": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "spec": {"type": "object"},
            "alt": {"type": "string"},
            "title": {"type": "string"},
            "caption": {"type": "string"},
        }
    ),
    "tikz_to_svg": _obj(
        {
            "knowledge_point": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "tikz": {"type": "string"},
            "preamble": {"type": "string"},
            "alt": {"type": "string"},
            "title": {"type": "string"},
            "caption": {"type": "string"},
        }
    ),
    "asy_to_svg": _obj(
        {
            "knowledge_point": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "asy": {"type": "string"},
            "asymptote": {"type": "string"},
            "code": {"type": "string"},
            "text": {"type": "string"},
            "alt": {"type": "string"},
            "title": {"type": "string"},
            "caption": {"type": "string"},
        }
    ),
    "seedream_generate": _obj(
        {
            "knowledge_point": {"type": "string"},
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "prompt": {"type": "string"},
            "size": {"type": "string"},
            "n": {"type": "integer", "minimum": 1, "maximum": 4},
            "model": {"type": "string"},
            "response_format": {"type": "string"},
            "alt": {"type": "string"},
            "title": {"type": "string"},
            "caption": {"type": "string"},
        }
    ),

    # plotting
    "plot_function": _obj(
        {
            "expr": {"type": "string"},
            "var": {"type": "string"},
            "xmin": {"type": "number"},
            "xmax": {"type": "number"},
            "title": {"type": "string"},
        }
    ),
    "plot_3d": _obj(
        {
            "expr": {"type": "string"},
            "xvar": {"type": "string"},
            "yvar": {"type": "string"},
            "xmin": {"type": "number"},
            "xmax": {"type": "number"},
            "ymin": {"type": "number"},
            "ymax": {"type": "number"},
            "title": {"type": "string"},
        }
    ),
}


def get_tool_input_schema(tool_name: str) -> Dict[str, Any]:
    name = str(tool_name or "").strip()
    schema = TOOL_INPUT_SCHEMAS.get(name)
    if isinstance(schema, dict) and schema:
        return dict(schema)
    return {"type": "object", "additionalProperties": True}
