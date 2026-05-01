from __future__ import annotations

import unittest

from backend.generation.agentic.types import (
    AgentArtifactRef,
    AgentBudget,
    AgentRoleSpec,
    AgentRunResult,
    AgentRunSpec,
    AgentSearchPolicy,
    AgentToolPolicy,
    AgentTraceEvent,
)


class AgenticTypesTests(unittest.TestCase):
    def test_agent_run_spec_round_trips_to_dict(self) -> None:
        spec = AgentRunSpec(
            domain="study_materials",
            goal="生成函数单调性自学资料",
            subject="高中数学",
            user_requirements="偏直观",
            input_payload={"topic": "函数单调性"},
            roles=[
                AgentRoleSpec(name="planner", prompt_id="agent.planner.study_materials.v1"),
                AgentRoleSpec(name="writer", prompt_id="study.material.writer.v1"),
            ],
            tool_policy=AgentToolPolicy(allowed_tools=["web_search_knowledge", "generate_study_material"]),
            search_policy=AgentSearchPolicy(),
            budget=AgentBudget(max_llm_calls=8, max_tool_calls=12, max_iterations=5),
            output_contract={"kind": "markdown"},
            resume_state={"last_stage": "search"},
        )

        data = spec.to_dict()
        restored = AgentRunSpec.from_dict(data)

        self.assertEqual(restored.domain, "study_materials")
        self.assertEqual(restored.input_payload["topic"], "函数单调性")
        self.assertEqual(restored.roles[0].name, "planner")
        self.assertEqual(restored.tool_policy.allowed_tools, ["web_search_knowledge", "generate_study_material"])
        self.assertEqual(restored.search_policy.providers[0], "tavily")
        self.assertEqual(restored.budget.max_llm_calls, 8)

    def test_trace_event_maps_to_task_event_shape(self) -> None:
        event = AgentTraceEvent(
            event="tool_call",
            role="researcher",
            step_id="s1",
            data={"name": "web_search_knowledge", "arguments": {"topic": "函数"}},
        )

        task_event = event.to_task_event(seq=3)

        self.assertEqual(task_event["seq"], 3)
        self.assertEqual(task_event["event"], "tool_call")
        self.assertEqual(task_event["data"]["role"], "researcher")
        self.assertEqual(task_event["data"]["step_id"], "s1")
        self.assertEqual(task_event["data"]["name"], "web_search_knowledge")

    def test_run_result_round_trips_artifacts(self) -> None:
        result = AgentRunResult(
            status="completed",
            summary="完成",
            artifacts=[
                AgentArtifactRef(
                    artifact_id="a1",
                    kind="markdown",
                    title="资料",
                    url="/media/a1.md",
                    metadata={"chars": 1200},
                )
            ],
            trace_summary={"tool_calls": 3},
        )

        restored = AgentRunResult.from_dict(result.to_dict())

        self.assertEqual(restored.status, "completed")
        self.assertEqual(restored.artifacts[0].kind, "markdown")
        self.assertEqual(restored.trace_summary["tool_calls"], 3)


if __name__ == "__main__":
    unittest.main()
