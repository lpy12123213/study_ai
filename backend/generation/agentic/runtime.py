from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Dict, List

from backend.generation.agentic.tooling import PlannerAgent, ToolExecutor, ToolResult
from backend.generation.agentic.types import AgentArtifactRef, AgentRunResult, AgentRunSpec, AgentTraceEvent


class AgentRuntime:
    """Minimal agentic runtime skeleton.

    The runtime is intentionally small at this stage: it executes planner
    decisions, enforces budgets, emits trace events, and collects final result
    metadata. Domain migrations can plug in richer planner/reviewer behavior
    without changing `/api/tasks`.
    """

    def __init__(self, *, planner: PlannerAgent, tool_executor: ToolExecutor) -> None:
        self.planner = planner
        self.tool_executor = tool_executor

    async def run(self, spec: AgentRunSpec) -> AsyncIterator[AgentTraceEvent]:
        state: Dict[str, Any] = {
            "llm_calls": 0,
            "tool_calls": 0,
            "iterations": 0,
            "failures": [],
            "artifacts": [],
            "search_policy": spec.search_policy.to_dict(),
        }
        start_time = time.monotonic()

        while state["iterations"] < spec.budget.max_iterations:
            state["iterations"] += 1

            if spec.budget.max_runtime_s and (time.monotonic() - start_time) > spec.budget.max_runtime_s:
                yield AgentTraceEvent(event="error", data={"error": "runtime_budget_exceeded"})
                return

            if state["llm_calls"] >= spec.budget.max_llm_calls:
                yield AgentTraceEvent(event="error", data={"error": "llm_budget_exceeded"})
                return

            try:
                decision = await self.planner.next_decision(spec=spec, state=state)
            except asyncio.CancelledError:
                yield AgentTraceEvent(event="error", data={"error": "agent_run_canceled"})
                return

            state["llm_calls"] += 1
            if decision.action == "finish":
                yield AgentTraceEvent(
                    event="finish",
                    role=decision.role,
                    step_id=decision.step_id,
                    data={"summary": decision.summary or "completed"},
                )
                return

            yield AgentTraceEvent(
                event="agent_decision",
                role=decision.role,
                step_id=decision.step_id,
                data=decision.to_event_data(),
            )

            if decision.action != "tool":
                yield AgentTraceEvent(
                    event="error",
                    role=decision.role,
                    step_id=decision.step_id,
                    data={"error": f"unsupported_agent_action: {decision.action}"},
                )
                return

            tool_name = str(decision.tool_name or "").strip()
            if not tool_name:
                yield AgentTraceEvent(
                    event="error",
                    role=decision.role,
                    step_id=decision.step_id,
                    data={"error": "missing_tool_name"},
                )
                return

            allowed = [str(x or "").strip() for x in spec.tool_policy.allowed_tools if str(x or "").strip()]
            excluded = {str(x or "").strip() for x in spec.tool_policy.excluded_tools if str(x or "").strip()}
            if (allowed and tool_name not in allowed) or tool_name in excluded:
                yield AgentTraceEvent(
                    event="error",
                    role=decision.role,
                    step_id=decision.step_id,
                    data={"error": f"tool_not_allowed: {tool_name}"},
                )
                return

            if state["tool_calls"] >= spec.budget.max_tool_calls:
                yield AgentTraceEvent(
                    event="error",
                    role=decision.role,
                    step_id=decision.step_id,
                    data={"error": "tool_budget_exceeded", "name": tool_name},
                )
                return

            yield AgentTraceEvent(
                event="tool_call",
                role=decision.role,
                step_id=decision.step_id,
                data={"name": tool_name, "arguments": dict(decision.arguments), "thought": decision.thought or ""},
            )

            try:
                result = await self.tool_executor.execute_tool(
                    name=tool_name,
                    arguments=dict(decision.arguments),
                    spec=spec,
                    state=state,
                )
            except asyncio.CancelledError:
                yield AgentTraceEvent(event="error", role=decision.role, step_id=decision.step_id, data={"error": "agent_run_canceled"})
                return

            state["tool_calls"] += 1
            self._collect_artifacts(state, result)
            yield AgentTraceEvent(
                event="tool_result",
                role=decision.role,
                step_id=decision.step_id,
                data=result.to_event_data(name=tool_name, arguments=dict(decision.arguments)),
            )

            if not result.success:
                failure = {"name": tool_name, "error": result.error or "tool_failed", "arguments": dict(decision.arguments)}
                state["failures"].append(failure)
                if len(state["failures"]) >= max(1, int(spec.tool_policy.max_consecutive_failures or 1)):
                    yield AgentTraceEvent(
                        event="error",
                        role=decision.role,
                        step_id=decision.step_id,
                        data={"error": "tool_failure_limit_exceeded", "failure": failure},
                    )
                    return
                yield AgentTraceEvent(
                    event="retry",
                    role=decision.role,
                    step_id=decision.step_id,
                    data={"reason": result.error or "tool_failed", "previous_tool": tool_name},
                )
            else:
                state["failures"] = []

        yield AgentTraceEvent(event="error", data={"error": "iteration_budget_exceeded"})

    async def run_to_result(self, spec: AgentRunSpec) -> AgentRunResult:
        events: List[AgentTraceEvent] = []
        artifacts: List[AgentArtifactRef] = []
        summary = ""
        error = ""
        status = "failed"

        async for event in self.run(spec):
            events.append(event)
            if event.event == "finish":
                status = "completed"
                summary = str(event.data.get("summary") or "")
            elif event.event == "error":
                error = str(event.data.get("error") or "agent_run_failed")
                status = "canceled" if error == "agent_run_canceled" else "failed"
                break

            artifacts.extend(_artifacts_from_event(event))

        trace_summary = {
            "events": len(events),
            "tool_calls": len([event for event in events if event.event == "tool_call"]),
            "retries": len([event for event in events if event.event == "retry"]),
            "reviews": len([event for event in events if event.event == "review"]),
        }
        return AgentRunResult(
            status=status,
            summary=summary,
            artifacts=_dedupe_artifacts(artifacts),
            trace_summary=trace_summary,
            error=error,
        )

    @staticmethod
    def _collect_artifacts(state: Dict[str, Any], result: ToolResult) -> None:
        artifacts = state.get("artifacts")
        if not isinstance(artifacts, list):
            artifacts = []
            state["artifacts"] = artifacts
        artifacts.extend([artifact.to_dict() for artifact in result.artifacts])
        output = result.output if isinstance(result.output, dict) else {}
        out_artifacts = output.get("artifacts") if isinstance(output.get("artifacts"), list) else []
        artifacts.extend([x for x in out_artifacts if isinstance(x, dict)])


def _artifacts_from_event(event: AgentTraceEvent) -> List[AgentArtifactRef]:
    raw: List[Any] = []
    if isinstance(event.data.get("artifacts"), list):
        raw.extend(event.data.get("artifacts") or [])
    output = event.data.get("output")
    if isinstance(output, dict) and isinstance(output.get("artifacts"), list):
        raw.extend(output.get("artifacts") or [])
    out: List[AgentArtifactRef] = []
    for item in raw:
        if isinstance(item, AgentArtifactRef):
            out.append(item)
        elif isinstance(item, dict):
            out.append(AgentArtifactRef.from_dict(item))
    return out


def _dedupe_artifacts(artifacts: List[AgentArtifactRef]) -> List[AgentArtifactRef]:
    seen: set[str] = set()
    out: List[AgentArtifactRef] = []
    for artifact in artifacts:
        key = artifact.artifact_id or f"{artifact.kind}:{artifact.url}:{artifact.path}"
        if key in seen:
            continue
        seen.add(key)
        out.append(artifact)
    return out
