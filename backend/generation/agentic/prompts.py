from __future__ import annotations

"""Compatibility re-export for the canonical LLM prompt registry.

The implementation lives in `backend.llm.prompts.agentic_registry`. Keep this
module thin while callers migrate to `backend.llm.prompts`.
"""

from backend.llm.prompts.agentic_registry import (
    EDU_MATH_FORMAT_GUARDRAIL,
    JSON_ONLY_GUARDRAIL,
    LANGUAGE_MATCH_GUARDRAIL,
    NO_HIDDEN_COT_GUARDRAIL,
    NO_MARKDOWN_FENCE_GUARDRAIL,
    NO_URL_IN_MARKDOWN_GUARDRAIL,
    ORIGINAL_REWRITE_GUARDRAIL,
    PROMPT_INVENTORY_ALLOWLIST,
    PROMPT_INVENTORY_TARGETS,
    SOURCE_GROUNDING_GUARDRAIL,
    PromptRegistry,
    PromptRenderResult,
    PromptTemplate,
    create_default_prompt_registry,
    repo_root_from_here,
)

__all__ = [
    "EDU_MATH_FORMAT_GUARDRAIL",
    "JSON_ONLY_GUARDRAIL",
    "LANGUAGE_MATCH_GUARDRAIL",
    "NO_HIDDEN_COT_GUARDRAIL",
    "NO_MARKDOWN_FENCE_GUARDRAIL",
    "NO_URL_IN_MARKDOWN_GUARDRAIL",
    "ORIGINAL_REWRITE_GUARDRAIL",
    "PROMPT_INVENTORY_ALLOWLIST",
    "PROMPT_INVENTORY_TARGETS",
    "SOURCE_GROUNDING_GUARDRAIL",
    "PromptRegistry",
    "PromptRenderResult",
    "PromptTemplate",
    "create_default_prompt_registry",
    "repo_root_from_here",
]
