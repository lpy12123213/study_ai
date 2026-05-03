"""Agentic generation primitives.

This package is the canonical home for the new agent runtime, prompt registry,
and typed run specifications. Existing domain flows should migrate into this
package incrementally instead of creating parallel task runtimes.
"""

from backend.generation.agentic.prompts import PromptRegistry, PromptTemplate, create_default_prompt_registry
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
