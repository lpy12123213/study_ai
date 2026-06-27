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


if __name__ == "__main__":
    unittest.main()
