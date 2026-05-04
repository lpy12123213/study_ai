from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_request_id, get_trace_id


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
class PolicyState:
    """State owned by policy modules, kept separate from tool working memory."""

    auto_research_rounds: int = 0
    auto_research_done_kps: List[str] = field(default_factory=list)
    auto_revise_rounds: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "auto_research_rounds": int(self.auto_research_rounds or 0),
            "auto_research_done_kps": list(self.auto_research_done_kps or []),
            "auto_revise_rounds": int(self.auto_revise_rounds or 0),
        }

    def load_legacy(self, legacy: Dict[str, Any]) -> None:
        self.auto_research_rounds = int(legacy.get("auto_research_rounds") or self.auto_research_rounds or 0)
        self.auto_revise_rounds = int(legacy.get("auto_revise_rounds") or self.auto_revise_rounds or 0)
        done = legacy.get("auto_research_done_kps")
        if isinstance(done, list) and not self.auto_research_done_kps:
            out: List[str] = []
            seen: set[str] = set()
            for kp in done:
                value = str(kp or "").strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                out.append(value)
                if len(out) >= 100:
                    break
            self.auto_research_done_kps = out


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
    working_memory_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)
    policy_state: PolicyState = field(default_factory=PolicyState)

    def __post_init__(self) -> None:
        legacy_policy_state = self.working_memory.pop("_study_policy", None)
        if isinstance(legacy_policy_state, dict):
            self.policy_state.load_legacy(legacy_policy_state)

    def get_working_value(self, key: str, default: Any = None) -> Any:
        return self.working_memory.get(key, default)

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
                "policy_state": self.policy_state.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )


def agent_event(event: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event": event, "data": data or {}}
    trace_id = get_trace_id() or get_request_id()
    if trace_id:
        payload["trace_id"] = trace_id
    return payload
