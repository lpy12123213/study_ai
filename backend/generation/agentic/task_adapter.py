from __future__ import annotations

from typing import Any, Dict, Optional

from backend.generation.agentic.types import AgentTraceEvent


def agent_trace_to_task_event(event: AgentTraceEvent, *, seq: Optional[int] = None) -> Dict[str, Any]:
    return event.to_task_event(seq=seq)


def progress_from_agent_event(event: AgentTraceEvent) -> int:
    mapping = {
        "agent_thought": 10,
        "agent_decision": 15,
        "tool_call": 25,
        "tool_result": 45,
        "retry": 50,
        "quality_gate": 70,
        "review": 75,
        "artifact": 85,
        "finish": 100,
        "error": 100,
    }
    return mapping.get(event.event, 0)
