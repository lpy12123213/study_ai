from __future__ import annotations

import unittest
from typing import Any

from backend.agent.types import StepResult


class _FakeExecutor:
    def __init__(self, *, fail_tools: set[str] | None = None) -> None:
        self.calls: list[Any] = []
        self.fail_tools = set(fail_tools or set())

    async def execute_step(self, step, *, context, emit_event=None):
        self.calls.append(step)
        point = str((step.arguments.get("knowledge_points") or [step.arguments.get("knowledge_point") or ""])[0])
        if step.tool in self.fail_tools:
            return StepResult(step_id=step.id, tool=step.tool, success=False, error="simulated_outage")
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
    async def test_extra_research_options_are_persisted_and_used(self) -> None:
        from backend.generation.study_materials.tool_executor import StudyMaterialsToolExecutor

        executor = _FakeExecutor()
        adapter = StudyMaterialsToolExecutor(
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            user_id="u-1",
            options={
                "with_questions": True,
                "with_diagrams": False,
                "enable_extra_tools": True,
                "max_points": 2,
            },
            executor=executor,
            context_manager=_FakeContextManager(),
        )

        async def sink(_event: dict) -> None:
            return None

        await adapter.research(
            plan={"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]},
            event_sink=sink,
        )

        self.assertEqual(
            [step.tool for step in executor.calls],
            ["web_search_knowledge", "wikipedia_search", "stackexchange_search", "github_search"],
        )
        self.assertTrue(adapter.working_memory["study_options"]["with_questions"])
        self.assertFalse(adapter.working_memory["study_options"]["with_diagrams"])
        self.assertEqual(adapter.working_memory["study_options"]["max_points"], 2)

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

    async def test_retry_rotates_query_hint_and_merges_existing_evidence(self) -> None:
        from backend.generation.study_materials.tool_executor import StudyMaterialsToolExecutor

        executor = _FakeExecutor()
        adapter = StudyMaterialsToolExecutor(
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            user_id="u-1",
            executor=executor,
            context_manager=_FakeContextManager(),
            resume_working_memory={
                "workflow_research": {
                    "kp-1": [
                        {
                            "source_class": "web",
                            "url": "https://example.test/legacy",
                            "title": "旧证据",
                            "snippet": "上一轮留下的证据。",
                        }
                    ],
                    "kp-2": [
                        {
                            "source_class": "wikipedia",
                            "url": "https://zh.wikipedia.org/wiki/减函数",
                            "title": "减函数",
                            "snippet": "减函数的百科定义。",
                        }
                    ],
                }
            },
        )

        async def sink(_event: dict) -> None:
            return None

        evidence = await adapter.research(
            plan={
                "knowledge_points": [
                    {"id": "kp-1", "title": "增函数", "queries": ["增函数 定义", "增函数 判定"]},
                    {"id": "kp-2", "title": "减函数", "queries": ["减函数 定义"]},
                ]
            },
            event_sink=sink,
            only_point_ids=["kp-1"],
            attempt=1,
        )

        # 只重查 kp-1，且 query_hint 轮换到 queries[1]。
        self.assertTrue(all("增函数" in (step.arguments.get("knowledge_points") or [""])[0] for step in executor.calls))
        web_steps = [step for step in executor.calls if step.tool == "web_search_knowledge"]
        self.assertEqual(web_steps[0].arguments["query_hint"], "增函数 判定")
        # 合并：kp-1 保留旧证据并追加新证据；kp-2 原样保留。
        self.assertIn("https://example.test/legacy", {item["url"] for item in evidence["kp-1"]})
        self.assertIn("wikipedia", {item["source_class"] for item in evidence["kp-1"]})
        self.assertEqual(evidence["kp-2"][0]["url"], "https://zh.wikipedia.org/wiki/减函数")

    async def test_consecutive_tool_failures_trip_research_outage(self) -> None:
        from backend.generation.study_materials.tool_executor import ResearchToolOutage, StudyMaterialsToolExecutor

        executor = _FakeExecutor(fail_tools={"web_search_knowledge"})
        adapter = StudyMaterialsToolExecutor(
            topic="函数单调性",
            subject="高中数学",
            preset="quick",
            user_id="u-1",
            executor=executor,
            context_manager=_FakeContextManager(),
        )

        async def sink(_event: dict) -> None:
            return None

        with self.assertRaises(ResearchToolOutage) as raised:
            await adapter.research(
                plan={
                    "knowledge_points": [
                        {"id": "kp-1", "title": "增函数", "queries": ["增函数"]},
                        {"id": "kp-2", "title": "减函数", "queries": ["减函数"]},
                        {"id": "kp-3", "title": "单调性", "queries": ["单调性"]},
                    ]
                },
                event_sink=sink,
            )

        self.assertIn("web_search_knowledge", raised.exception.tools)

    async def test_browse_failures_do_not_trip_research_outage(self) -> None:
        from backend.generation.study_materials.tool_executor import StudyMaterialsToolExecutor

        executor = _FakeExecutor(fail_tools={"browse_web_pages"})
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
        self.assertEqual({item["source_class"] for item in evidence["kp-1"]}, {"web", "wikipedia"})


class _WorkflowToolExecutor:
    def __init__(self, *, reviews: list[dict], enough_research: bool = True) -> None:
        self.reviews = list(reviews)
        self.enough_research = enough_research
        self.working_memory: dict = {}
        self.step_results: list[dict] = []
        self.research_calls = 0
        self.review_calls = 0
        self.research_kwargs: list[dict] = []

    async def research(self, *, plan: dict, event_sink, only_point_ids=None, attempt: int = 0) -> dict:
        self.research_calls += 1
        self.research_kwargs.append({"only_point_ids": only_point_ids, "attempt": attempt})
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
    async def test_stage_result_error_checkpoints_failed_stage(self) -> None:
        from backend.generation.study_materials.codex_stages import StageResultError
        from backend.generation.study_materials.workflow import StudyMaterialsWorkflow

        checkpoints: list[dict] = []

        async def stage_runner(**kwargs):
            raise StageResultError(
                "invalid_stage_result",
                stage=kwargs["stage"],
                detail="stage_contract_mismatch",
            )

        async def checkpoint(state: dict, _resume: dict) -> None:
            checkpoints.append(dict(state))

        workflow = StudyMaterialsWorkflow(
            task_id="task-stage-error",
            user_id="u-1",
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            resume_working_memory={
                "study_materials_workflow": {
                    "version": 1,
                    "stage": "draft",
                    "preset": "standard",
                    "plan": {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]},
                    "research": {},
                    "markdown": "",
                    "last_failure": {},
                }
            },
            stage_runner=stage_runner,
            tool_executor=_WorkflowToolExecutor(reviews=[]),
            checkpoint_sink=checkpoint,
        )

        with self.assertRaisesRegex(StageResultError, "invalid_stage_result"):
            await workflow.run()

        self.assertTrue(checkpoints)
        self.assertEqual(checkpoints[-1]["stage"], "draft")
        self.assertEqual(checkpoints[-1]["last_failure"]["stage"], "draft")
        self.assertEqual(checkpoints[-1]["last_failure"]["detail"], "stage_contract_mismatch")

    async def test_generation_options_reach_stage_runner_and_resume_memory(self) -> None:
        from backend.generation.study_materials.workflow import StudyMaterialsWorkflow

        options = {
            "preset": "quick",
            "requirements": "保留要求",
            "with_questions": True,
            "with_diagrams": False,
            "enable_extra_tools": True,
            "max_points": 2,
        }
        seen_options: list[dict] = []

        async def stage_runner(**kwargs):
            seen_options.append(dict(kwargs["options"]))
            if kwargs["stage"] == "plan":
                return {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]}
            return {
                "markdown": "# 函数单调性\n\n## 增函数\n\n定义、性质和例题。",
                "coverage_map": {"kp-1": True},
            }

        workflow = StudyMaterialsWorkflow(
            task_id="task-options",
            user_id="u-1",
            topic="函数单调性",
            subject="高中数学",
            preset="quick",
            requirements="保留要求",
            options=options,
            stage_runner=stage_runner,
            tool_executor=_WorkflowToolExecutor(reviews=[_passing_review()]),
        )

        result = await workflow.run()

        self.assertEqual(seen_options, [options, options])
        self.assertEqual(result["resume_working_memory"]["study_options"], options)

    async def test_revision_attempts_exhausted_with_markdown_delivers_degraded(self) -> None:
        from backend.generation.study_materials.workflow import StudyMaterialsWorkflow

        stages: list[str] = []
        events: list[dict] = []

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

        async def sink(event: dict) -> None:
            events.append(event)

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

        result = await workflow.run()

        self.assertEqual(stages, ["plan", "draft", "revise"])
        self.assertEqual(workflow.state["stage"], "completed")
        self.assertTrue(result["degraded"])
        self.assertFalse(result["material"]["passed"])
        self.assertTrue(result["material"]["issues"])
        self.assertFalse(workflow.state.get("acceptance", {}).get("accepted", False))
        self.assertEqual(result["acceptance"], {})
        degraded_events = [event for event in events if event.get("type") == "quality_degraded"]
        self.assertEqual(len(degraded_events), 1)
        self.assertEqual(degraded_events[0]["data"]["revision_attempts"], 1)

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
        events: list[dict] = []
        tool_executor = _WorkflowToolExecutor(reviews=[], enough_research=False)

        async def stage_runner(**kwargs):
            stages.append(kwargs["stage"])
            return {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]}

        async def sink(event: dict) -> None:
            events.append(event)

        async def checkpoint(_state: dict, _resume: dict) -> None:
            return None

        workflow = StudyMaterialsWorkflow(
            task_id="task-no-research",
            user_id="u-1",
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            stage_runner=stage_runner,
            tool_executor=tool_executor,
            event_sink=sink,
            checkpoint_sink=checkpoint,
        )

        with self.assertRaisesRegex(WorkflowFailure, "quality_gate_not_met") as raised:
            await workflow.run()

        self.assertEqual(stages, ["plan"])
        self.assertEqual(raised.exception.stage, "research")
        # standard 允许 2 次检索重试：首次 + 2 次重试共 3 次调用后才失败。
        self.assertEqual(tool_executor.research_calls, 3)
        retry_events = [event for event in events if event.get("type") == "research_retry_required"]
        self.assertEqual(len(retry_events), 2)
        self.assertEqual(retry_events[0]["data"]["point_ids"], ["kp-1"])

    async def test_research_tool_outage_fails_with_recoverable_outage_code(self) -> None:
        from backend.generation.study_materials.tool_executor import ResearchToolOutage
        from backend.generation.study_materials.workflow import StudyMaterialsWorkflow, WorkflowFailure

        class _OutageToolExecutor(_WorkflowToolExecutor):
            async def research(self, *, plan: dict, event_sink, only_point_ids=None, attempt: int = 0) -> dict:
                raise ResearchToolOutage(["web_search_knowledge", "wikipedia_search", "web_search_knowledge"])

        async def stage_runner(**kwargs):
            return {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]}

        async def sink(_event: dict) -> None:
            return None

        async def checkpoint(_state: dict, _resume: dict) -> None:
            return None

        workflow = StudyMaterialsWorkflow(
            task_id="task-outage",
            user_id="u-1",
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            stage_runner=stage_runner,
            tool_executor=_OutageToolExecutor(reviews=[]),
            event_sink=sink,
            checkpoint_sink=checkpoint,
        )

        with self.assertRaisesRegex(WorkflowFailure, "research_tool_outage") as raised:
            await workflow.run()

        self.assertEqual(raised.exception.stage, "research")
        self.assertTrue(raised.exception.recoverable)
        self.assertIn("tool_unavailable:web_search_knowledge", raised.exception.issues)
        self.assertEqual(workflow.state["last_failure"]["code"], "research_tool_outage")


if __name__ == "__main__":
    unittest.main()
