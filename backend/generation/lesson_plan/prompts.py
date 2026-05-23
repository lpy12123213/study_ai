from __future__ import annotations

from backend.generation.agentic.prompts import create_default_prompt_registry


def get_system_prompt() -> str:
    return create_default_prompt_registry().render("lesson_plan.writer.v1").content


SYSTEM_PROMPT = get_system_prompt()
