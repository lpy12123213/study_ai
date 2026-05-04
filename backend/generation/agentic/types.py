from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

AGENTIC_DOMAINS = {
    "study_materials",
    "question_generation",
    "deepthink",
    "lesson_plan",
    "paper_compose",
    "knowledge_video",
    "question_evaluate",
    "chat",
    "mcp",
}

AGENT_TRACE_EVENTS = {
    "agent_thought",
    "agent_decision",
    "tool_call",
    "tool_result",
    "quality_gate",
    "artifact",
    "review",
    "retry",
    "finish",
    "error",
}


def _now_s() -> float:
    return time.time()


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


@dataclass(frozen=True)
class AgentRoleSpec:
    name: str
    prompt_id: str
    model: str = ""
    instructions: str = ""
    required: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "prompt_id": self.prompt_id,
            "model": self.model,
            "instructions": self.instructions,
            "required": bool(self.required),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentRoleSpec":
        d = _dict(data)
        return cls(
            name=str(d.get("name") or "").strip(),
            prompt_id=str(d.get("prompt_id") or "").strip(),
            model=str(d.get("model") or "").strip(),
            instructions=str(d.get("instructions") or ""),
            required=bool(d.get("required", True)),
            metadata=_dict(d.get("metadata")),
        )


@dataclass(frozen=True)
class AgentSearchPolicy:
    providers: List[str] = field(default_factory=lambda: ["tavily", "exa", "metaso", "bigmodel"])
    max_results: int = 8
    allow_fallback: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "providers": list(self.providers),
            "max_results": int(self.max_results),
            "allow_fallback": bool(self.allow_fallback),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "AgentSearchPolicy":
        d = _dict(data)
        providers = [str(x or "").strip() for x in _list(d.get("providers")) if str(x or "").strip()]
        return cls(
            providers=providers or ["tavily", "exa", "metaso", "bigmodel"],
            max_results=int(d.get("max_results") or 8),
            allow_fallback=bool(d.get("allow_fallback", True)),
            metadata=_dict(d.get("metadata")),
        )


@dataclass(frozen=True)
class AgentToolPolicy:
    allowed_tools: List[str] = field(default_factory=list)
    excluded_tools: List[str] = field(default_factory=list)
    allow_parallel: bool = True
    max_consecutive_failures: int = 2
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed_tools": list(self.allowed_tools),
            "excluded_tools": list(self.excluded_tools),
            "allow_parallel": bool(self.allow_parallel),
            "max_consecutive_failures": int(self.max_consecutive_failures),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "AgentToolPolicy":
        d = _dict(data)
        return cls(
            allowed_tools=[str(x or "").strip() for x in _list(d.get("allowed_tools")) if str(x or "").strip()],
            excluded_tools=[str(x or "").strip() for x in _list(d.get("excluded_tools")) if str(x or "").strip()],
            allow_parallel=bool(d.get("allow_parallel", True)),
            max_consecutive_failures=int(d.get("max_consecutive_failures") or 2),
            metadata=_dict(d.get("metadata")),
        )


@dataclass(frozen=True)
class AgentBudget:
    max_llm_calls: int = 25
    max_tool_calls: int = 40
    max_iterations: int = 20
    max_runtime_s: int = 900

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_llm_calls": int(self.max_llm_calls),
            "max_tool_calls": int(self.max_tool_calls),
            "max_iterations": int(self.max_iterations),
            "max_runtime_s": int(self.max_runtime_s),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "AgentBudget":
        d = _dict(data)
        return cls(
            max_llm_calls=int(d.get("max_llm_calls") or 25),
            max_tool_calls=int(d.get("max_tool_calls") or 40),
            max_iterations=int(d.get("max_iterations") or 20),
            max_runtime_s=int(d.get("max_runtime_s") or 900),
        )


@dataclass(frozen=True)
class AgentArtifactRef:
    artifact_id: str
    kind: str
    title: str = ""
    url: str = ""
    path: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "path": self.path,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentArtifactRef":
        d = _dict(data)
        return cls(
            artifact_id=str(d.get("artifact_id") or "").strip(),
            kind=str(d.get("kind") or "").strip(),
            title=str(d.get("title") or ""),
            url=str(d.get("url") or ""),
            path=str(d.get("path") or ""),
            metadata=_dict(d.get("metadata")),
        )


@dataclass(frozen=True)
class AgentTraceEvent:
    event: str
    data: Dict[str, Any] = field(default_factory=dict)
    role: str = ""
    step_id: str = ""
    ts: float = field(default_factory=_now_s)

    def __post_init__(self) -> None:
        if self.event not in AGENT_TRACE_EVENTS:
            raise ValueError(f"invalid_agent_trace_event: {self.event}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event,
            "role": self.role,
            "step_id": self.step_id,
            "ts": float(self.ts),
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentTraceEvent":
        d = _dict(data)
        return cls(
            event=str(d.get("event") or "").strip(),
            role=str(d.get("role") or "").strip(),
            step_id=str(d.get("step_id") or "").strip(),
            ts=float(d.get("ts") or _now_s()),
            data=_dict(d.get("data")),
        )

    def to_task_event(self, *, seq: Optional[int] = None) -> Dict[str, Any]:
        payload = dict(self.data)
        if self.role:
            payload.setdefault("role", self.role)
        if self.step_id:
            payload.setdefault("step_id", self.step_id)
        event: Dict[str, Any] = {
            "event": self.event,
            "type": self.event,
            "data": payload,
            "ts": float(self.ts),
        }
        if seq is not None:
            event["seq"] = int(seq)
        return event


@dataclass(frozen=True)
class AgentRunSpec:
    domain: str
    goal: str
    subject: str = ""
    user_requirements: str = ""
    input_payload: Dict[str, Any] = field(default_factory=dict)
    roles: List[AgentRoleSpec] = field(default_factory=list)
    tool_policy: AgentToolPolicy = field(default_factory=AgentToolPolicy)
    search_policy: AgentSearchPolicy = field(default_factory=AgentSearchPolicy)
    budget: AgentBudget = field(default_factory=AgentBudget)
    output_contract: Dict[str, Any] = field(default_factory=dict)
    resume_state: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.domain not in AGENTIC_DOMAINS:
            raise ValueError(f"invalid_agent_domain: {self.domain}")
        if not str(self.goal or "").strip():
            raise ValueError("missing_agent_goal")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "goal": self.goal,
            "subject": self.subject,
            "user_requirements": self.user_requirements,
            "input_payload": dict(self.input_payload),
            "roles": [role.to_dict() for role in self.roles],
            "tool_policy": self.tool_policy.to_dict(),
            "search_policy": self.search_policy.to_dict(),
            "budget": self.budget.to_dict(),
            "output_contract": dict(self.output_contract),
            "resume_state": dict(self.resume_state),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentRunSpec":
        d = _dict(data)
        return cls(
            domain=str(d.get("domain") or "").strip(),
            goal=str(d.get("goal") or "").strip(),
            subject=str(d.get("subject") or ""),
            user_requirements=str(d.get("user_requirements") or ""),
            input_payload=_dict(d.get("input_payload")),
            roles=[AgentRoleSpec.from_dict(x) for x in _list(d.get("roles")) if isinstance(x, dict)],
            tool_policy=AgentToolPolicy.from_dict(d.get("tool_policy")),
            search_policy=AgentSearchPolicy.from_dict(d.get("search_policy")),
            budget=AgentBudget.from_dict(d.get("budget")),
            output_contract=_dict(d.get("output_contract")),
            resume_state=_dict(d.get("resume_state")),
            metadata=_dict(d.get("metadata")),
        )


@dataclass(frozen=True)
class AgentRunResult:
    status: str
    summary: str = ""
    artifacts: List[AgentArtifactRef] = field(default_factory=list)
    trace_summary: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "trace_summary": dict(self.trace_summary),
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentRunResult":
        d = _dict(data)
        return cls(
            status=str(d.get("status") or "").strip(),
            summary=str(d.get("summary") or ""),
            artifacts=[AgentArtifactRef.from_dict(x) for x in _list(d.get("artifacts")) if isinstance(x, dict)],
            trace_summary=_dict(d.get("trace_summary")),
            error=str(d.get("error") or ""),
            metadata=_dict(d.get("metadata")),
        )
