from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol

from backend.generation.agentic.types import AgentArtifactRef, AgentRunSpec


@dataclass(frozen=True)
class AgentDecision:
    action: str
    thought: str = ""
    role: str = "planner"
    step_id: str = ""
    tool_name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def tool(
        cls,
        *,
        name: str,
        arguments: Dict[str, Any] | None = None,
        thought: str = "",
        role: str = "planner",
        step_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> "AgentDecision":
        return cls(
            action="tool",
            thought=thought,
            role=role,
            step_id=step_id,
            tool_name=str(name or "").strip(),
            arguments=dict(arguments or {}),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def finish(cls, *, summary: str = "", role: str = "planner", metadata: Dict[str, Any] | None = None) -> "AgentDecision":
        return cls(action="finish", summary=str(summary or ""), role=role, metadata=dict(metadata or {}))

    def to_event_data(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "action": self.action,
            "thought": self.thought,
        }
        if self.tool_name:
            data["name"] = self.tool_name
            data["arguments"] = dict(self.arguments)
        if self.summary:
            data["summary"] = self.summary
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


@dataclass(frozen=True)
class ToolResult:
    success: bool
    output: Any = None
    error: str = ""
    artifacts: List[AgentArtifactRef] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_event_data(self, *, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "name": name,
            "arguments": dict(arguments),
            "success": bool(self.success),
        }
        if self.output is not None:
            data["output"] = self.output
        if self.error:
            data["error"] = self.error
        if self.artifacts:
            data["artifacts"] = [artifact.to_dict() for artifact in self.artifacts]
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


class PlannerAgent(Protocol):
    async def next_decision(self, *, spec: AgentRunSpec, state: Dict[str, Any]) -> AgentDecision:
        ...


class ToolExecutor(Protocol):
    async def execute_tool(
        self,
        *,
        name: str,
        arguments: Dict[str, Any],
        spec: AgentRunSpec,
        state: Dict[str, Any],
    ) -> ToolResult:
        ...


class ReviewerAgent(Protocol):
    async def review(self, *, spec: AgentRunSpec, state: Dict[str, Any]) -> Dict[str, Any]:
        ...


class ArtifactWriter(Protocol):
    async def write_artifact(self, *, spec: AgentRunSpec, artifact: AgentArtifactRef) -> AgentArtifactRef:
        ...
