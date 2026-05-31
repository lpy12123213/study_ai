"""Agentic generation primitives."""

from backend.generation.agentic.task_specs import build_agent_run_spec_for_task, build_agentic_starter_event
from backend.generation.agentic.types import AgentRunSpec, AgentTraceEvent

__all__ = [
    "AgentRunSpec",
    "AgentTraceEvent",
    "PromptRegistry",
    "PromptTemplate",
    "build_agent_run_spec_for_task",
    "build_agentic_starter_event",
    "create_default_prompt_registry",
]


def __getattr__(name: str):
    if name in {"PromptRegistry", "PromptTemplate", "create_default_prompt_registry"}:
        from backend.generation.agentic import prompts

        return getattr(prompts, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
