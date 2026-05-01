"""
DeepThink prompts.

These templates are formatted with:
- {subject}: 学科/领域名称（如：高中数学）
"""

from __future__ import annotations

from backend.generation.agentic.prompts import create_default_prompt_registry


def _template(prompt_id: str) -> str:
    return create_default_prompt_registry().get(prompt_id).template


GENERATOR_SYSTEM_PROMPT_TEMPLATE = _template("deepthink.generator.v1")
EVALUATOR_SYSTEM_PROMPT_TEMPLATE = _template("deepthink.evaluator.v1")
SYNTHESIZER_SYSTEM_PROMPT_TEMPLATE = _template("deepthink.synthesizer.v1")


def get_generator_system_prompt(subject: str) -> str:
    return create_default_prompt_registry().render("deepthink.generator.v1", subject=subject).content


def get_evaluator_system_prompt(subject: str) -> str:
    return create_default_prompt_registry().render("deepthink.evaluator.v1", subject=subject).content


def get_synthesizer_system_prompt(subject: str) -> str:
    return create_default_prompt_registry().render("deepthink.synthesizer.v1", subject=subject).content
