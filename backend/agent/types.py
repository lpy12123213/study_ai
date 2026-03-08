from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    ACTING = "acting"
    REFLECTING = "reflecting"
    COMPRESSING = "compressing"
    WAITING_TOOL = "waiting_tool"
    ITERATING = "iterating"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class PlanStep:
    """A single executable step in an execution plan."""

    id: str
    title: str
    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    parallel_group: str = ""
    # A short user-facing explanation shown before tool execution.
    thought: str = ""
    # Expand this step into multiple steps, one per knowledge point from `split_knowledge_points`.
    foreach_knowledge_point: bool = False
    # Optional cap when `foreach_knowledge_point=True` (0 => no cap).
    foreach_limit: int = 0


@dataclass
class ExecutionPlan:
    """Plan output from the Planner."""

    topic: str
    steps: List[PlanStep]
    rationale: str = ""


@dataclass
class StepResult:
    step_id: str
    tool: str
    success: bool
    output: Any = None
    error: str = ""


@dataclass
class ActionResults:
    """All results produced by executing a plan."""

    step_results: List[StepResult] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReflectionResult:
    passed: bool
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class UserProfile:
    """A minimal user profile used for personalization and memory."""

    user_id: str
    ability_level: str = "unknown"  # e.g. beginner/intermediate/advanced/unknown
    ability_score: float = 0.5  # 0..1
    preferences: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "ability_level": self.ability_level,
            "ability_score": self.ability_score,
            "preferences": self.preferences,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        return cls(
            user_id=str(data.get("user_id") or "anonymous"),
            ability_level=str(data.get("ability_level") or "unknown"),
            ability_score=float(data.get("ability_score") or 0.5),
            preferences=dict(data.get("preferences") or {}),
            history=list(data.get("history") or []),
        )


@dataclass
class CompressedContext:
    """Conversation context with compaction layers (window/summary/checkpoint)."""

    user_profile: UserProfile
    system_instructions: str
    current_task: str

    checkpoint_summary: str = ""
    checkpoint_file: str = ""

    compressed_history: List[Dict[str, Any]] = field(default_factory=list)
    recent_messages: List[Dict[str, Any]] = field(default_factory=list)
    working_memory: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "user_profile": self.user_profile.to_dict(),
                "system_instructions": self.system_instructions,
                "current_task": self.current_task,
                "checkpoint_summary": self.checkpoint_summary,
                "checkpoint_file": self.checkpoint_file,
                "compressed_history": self.compressed_history,
                "recent_messages": self.recent_messages,
                "working_memory": self.working_memory,
            },
            ensure_ascii=False,
            indent=2,
        )


def agent_event(event: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"event": event, "data": data or {}}
