from __future__ import annotations

import unittest
from typing import Any

from backend.agent.types import StepResult


class _FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def execute_step(self, step, *, context, emit_event=None):
        self.calls.append(step)
        point = str((step.arguments.get("knowledge_points") or [step.arguments.get("knowledge_point") or ""])[0])
        if step.tool == "web_search_knowledge":
            output = {
                "items": [
                    {
                        "knowledge_point": point,
                        "results": [
                            {
                                "title": f"{point} web",
                                "url": f"https://example.test/{len(self.calls)}",
                                "snippet": f"{point} 的定义和判定。",
                            }
                        ],
                    }
                ]
            }
        elif step.tool == "wikipedia_search":
            output = {
                "items": [
                    {
                        "knowledge_point": point,
                        "title": point,
                        "url": f"https://zh.wikipedia.org/wiki/{point}",
                        "summary": f"{point} 的百科定义。",
                    }
                ]
            }
        elif step.tool == "mediawiki_search":
            output = {
                "items": [
                    {
                        "knowledge_point": point,
                        "title": point,
                        "url": f"https://baike.example/{point}",
                        "summary": f"{point} 的术语解释。",
                    }
                ]
            }
        elif step.tool == "browse_web_pages":
            output = {
                "knowledge_point": point,
                "pages": [
                    {
                        "title": f"{point} page",
                        "url": str((step.arguments.get("urls") or [""])[0]),
                        "text": f"{point} 的完整页面正文。",
                    }
                ],
            }
        elif step.tool == "review_content":
            output = {
                "passed": True,
                "issues": [],
                "suggestions": [],
                "dimensions": {
                    point or "增函数": {
                        "present": ["定义/概念", "性质/结论", "条件/适用范围", "反例/边界", "应用/题型"],
                        "missing": [],
                    }
                },
            }
        else:
            output = {}
        return StepResult(step_id=step.id, tool=step.tool, success=True, output=output)


class _FakeContextManager:
    def __init__(self) -> None:
        self.results: list[StepResult] = []

    async def on_step_result(self, context, *, step, result) -> None:
        self.results.append(result)
        context.working_memory[step.tool] = result.output


class StudyMaterialsToolExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_standard_research_uses_web_and_wikipedia_and_normalizes_evidence(self) -> None:
        from backend.generation.study_materials.tool_executor import StudyMaterialsToolExecutor

        executor = _FakeExecutor()
        context_manager = _FakeContextManager()
        adapter = StudyMaterialsToolExecutor(
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            user_id="u-1",
            executor=executor,
            context_manager=context_manager,
        )
        events: list[dict] = []

        async def sink(event: dict) -> None:
            events.append(event)

        evidence = await adapter.research(
            plan={
                "knowledge_points": [
                    {"id": "kp-1", "title": "增函数", "queries": ["增函数 定义"]},
                ]
            },
            event_sink=sink,
        )

        self.assertEqual([step.tool for step in executor.calls], ["web_search_knowledge", "wikipedia_search"])
        self.assertEqual({item["source_class"] for item in evidence["kp-1"]}, {"web", "wikipedia"})
        self.assertEqual(len(context_manager.results), 2)
        self.assertEqual(len(events), 4)

    async def test_deep_research_deep_reads_the_first_web_result(self) -> None:
        from backend.generation.study_materials.tool_executor import StudyMaterialsToolExecutor

        executor = _FakeExecutor()
        adapter = StudyMaterialsToolExecutor(
            topic="函数单调性",
            subject="高中数学",
            preset="deep",
            user_id="u-1",
            executor=executor,
            context_manager=_FakeContextManager(),
        )

        async def sink(_event: dict) -> None:
            return None

        evidence = await adapter.research(
            plan={"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]},
            event_sink=sink,
        )

        self.assertEqual(
            [step.tool for step in executor.calls],
            ["web_search_knowledge", "wikipedia_search", "browse_web_pages"],
        )
        self.assertIn("page", {item["source_class"] for item in evidence["kp-1"]})

    async def test_review_uses_current_markdown_and_records_its_hash(self) -> None:
        from backend.generation.study_materials.quality_gate import draft_hash
        from backend.generation.study_materials.tool_executor import StudyMaterialsToolExecutor

        executor = _FakeExecutor()
        adapter = StudyMaterialsToolExecutor(
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            user_id="u-1",
            executor=executor,
            context_manager=_FakeContextManager(),
        )
        markdown = "# 函数单调性\n\n## 增函数\n\n定义、性质、条件、反例、例题。"

        async def sink(_event: dict) -> None:
            return None

        review = await adapter.review(markdown=markdown, event_sink=sink)

        self.assertEqual(executor.calls[-1].tool, "review_content")
        self.assertEqual(adapter.working_memory["markdown"], markdown)
        self.assertTrue(review["passed"])
        self.assertEqual(review["draft_hash"], draft_hash(markdown))


class _WorkflowToolExecutor:
    def __init__(self, *, reviews: list[dict], enough_research: bool = True) -> None:
        self.reviews = list(reviews)
        self.enough_research = enough_research
        self.working_memory: dict = {}
        self.step_results: list[dict] = []
        self.research_calls = 0
        self.review_calls = 0

    async def research(self, *, plan: dict, event_sink) -> dict:
        self.research_calls += 1
        if not self.enough_research:
            return {"kp-1": []}
        return {
            "kp-1": [
                {
                    "source_class": "web",
                    "url": "https://example.test/a",
                    "title": "增函数定义",
                    "snippet": "增函数的定义、性质和判定。",
                },
                {
                    "source_class": "wikipedia",
                    "url": "https://zh.wikipedia.org/wiki/单调函数",
                    "title": "单调函数",
                    "snippet": "单调函数的百科定义。",
                },
            ]
        }

    async def review(self, *, markdown: str, event_sink) -> dict:
        from backend.generation.study_materials.quality_gate import draft_hash

        self.review_calls += 1
        review = dict(self.reviews.pop(0))
        review["draft_hash"] = draft_hash(markdown)
        return review


def _passing_review() -> dict:
    return {
        "passed": True,
        "issues": [],
        "suggestions": [],
        "dimensions": {
            "增函数": {
                "present": ["定义/概念", "性质/结论", "条件/适用范围", "反例/边界", "应用/题型"],
                "missing": [],
            }
        },
    }


def _failing_review() -> dict:
    return {
        "passed": False,
        "issues": ["缺少适用条件"],
        "suggestions": ["补充条件"],
        "dimensions": {"增函数": {"present": ["定义/概念"], "missing": ["条件/适用范围"]}},
    }


class StudyMaterialsWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_codex_cannot_complete_before_independent_review_passes(self) -> None:
        from backend.generation.study_materials.workflow import StudyMaterialsWorkflow, WorkflowFailure

        stages: list[str] = []

        async def stage_runner(**kwargs):
            stage = kwargs["stage"]
            stages.append(stage)
            if stage == "plan":
                return {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]}
            return {
                "markdown": "# 函数单调性\n\n## 增函数\n\n定义与例题。",
                "coverage_map": {"kp-1": True},
                "resolved_issues": ["缺少适用条件"],
            }

        async def sink(_event: dict) -> None:
            return None

        async def checkpoint(_state: dict, _resume: dict) -> None:
            return None

        workflow = StudyMaterialsWorkflow(
            task_id="task-early",
            user_id="u-1",
            topic="函数单调性",
            subject="高中数学",
            preset="quick",
            stage_runner=stage_runner,
            tool_executor=_WorkflowToolExecutor(reviews=[_failing_review(), _failing_review()]),
            event_sink=sink,
            checkpoint_sink=checkpoint,
        )

        with self.assertRaisesRegex(WorkflowFailure, "quality_gate_not_met") as raised:
            await workflow.run()

        self.assertEqual(stages, ["plan", "draft", "revise"])
        self.assertNotEqual(workflow.state["stage"], "completed")
        self.assertTrue(raised.exception.recoverable)
        self.assertFalse(workflow.state.get("acceptance", {}).get("accepted", False))

    async def test_successful_workflow_completes_only_after_acceptance_gate(self) -> None:
        from backend.generation.study_materials.workflow import StudyMaterialsWorkflow

        stages: list[str] = []
        events: list[dict] = []
        checkpoints: list[dict] = []

        async def stage_runner(**kwargs):
            stage = kwargs["stage"]
            stages.append(stage)
            if stage == "plan":
                return {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]}
            return {
                "markdown": "# 函数单调性\n\n## 增函数\n\n定义、性质、条件、反例和例题。",
                "coverage_map": {"kp-1": True},
            }

        async def sink(event: dict) -> None:
            events.append(event)

        async def checkpoint(state: dict, _resume: dict) -> None:
            checkpoints.append(dict(state))

        workflow = StudyMaterialsWorkflow(
            task_id="task-pass",
            user_id="u-1",
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            stage_runner=stage_runner,
            tool_executor=_WorkflowToolExecutor(reviews=[_passing_review()]),
            event_sink=sink,
            checkpoint_sink=checkpoint,
        )

        result = await workflow.run()

        self.assertEqual(stages, ["plan", "draft"])
        self.assertEqual(workflow.state["stage"], "completed")
        self.assertTrue(result["acceptance"]["accepted"])
        self.assertTrue(result["quality_report"]["passed"])
        self.assertGreaterEqual(len(checkpoints), 5)
        self.assertIn("quality_report", [event.get("type") or event.get("event") for event in events])

    async def test_failed_review_is_revised_and_reviewed_again(self) -> None:
        from backend.generation.study_materials.workflow import StudyMaterialsWorkflow

        stages: list[str] = []
        tool_executor = _WorkflowToolExecutor(reviews=[_failing_review(), _passing_review()])

        async def stage_runner(**kwargs):
            stage = kwargs["stage"]
            stages.append(stage)
            if stage == "plan":
                return {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]}
            if stage == "draft":
                return {
                    "markdown": "# 函数单调性\n\n## 增函数\n\n定义和例题。",
                    "coverage_map": {"kp-1": True},
                }
            return {
                "markdown": "# 函数单调性\n\n## 增函数\n\n定义、性质、适用条件、反例和例题。",
                "coverage_map": {"kp-1": True},
                "resolved_issues": ["缺少适用条件"],
            }

        async def sink(_event: dict) -> None:
            return None

        async def checkpoint(_state: dict, _resume: dict) -> None:
            return None

        workflow = StudyMaterialsWorkflow(
            task_id="task-revise",
            user_id="u-1",
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            stage_runner=stage_runner,
            tool_executor=tool_executor,
            event_sink=sink,
            checkpoint_sink=checkpoint,
        )

        result = await workflow.run()

        self.assertEqual(stages, ["plan", "draft", "revise"])
        self.assertEqual(tool_executor.review_calls, 2)
        self.assertTrue(result["acceptance"]["accepted"])

    async def test_missing_research_fails_before_draft(self) -> None:
        from backend.generation.study_materials.workflow import StudyMaterialsWorkflow, WorkflowFailure

        stages: list[str] = []

        async def stage_runner(**kwargs):
            stages.append(kwargs["stage"])
            return {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]}

        async def sink(_event: dict) -> None:
            return None

        async def checkpoint(_state: dict, _resume: dict) -> None:
            return None

        workflow = StudyMaterialsWorkflow(
            task_id="task-no-research",
            user_id="u-1",
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            stage_runner=stage_runner,
            tool_executor=_WorkflowToolExecutor(reviews=[], enough_research=False),
            event_sink=sink,
            checkpoint_sink=checkpoint,
        )

        with self.assertRaisesRegex(WorkflowFailure, "quality_gate_not_met") as raised:
            await workflow.run()

        self.assertEqual(stages, ["plan"])
        self.assertEqual(raised.exception.stage, "research")


if __name__ == "__main__":
    unittest.main()
