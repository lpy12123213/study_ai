from __future__ import annotations

import unittest
from unittest.mock import patch


class StudyMaterialsCodexStageTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_plan_stage_requires_structured_knowledge_points(self) -> None:
        from backend.generation.study_materials.codex_stages import normalize_stage_result

        result = normalize_stage_result(
            "plan",
            {
                "stage": "plan",
                "stage_status": "completed",
                "stage_version": 1,
                "payload": {
                    "knowledge_points": [
                        {"id": "kp-1", "title": "增函数", "queries": ["增函数 定义"]},
                    ]
                },
            },
        )

        self.assertEqual(result["knowledge_points"][0]["id"], "kp-1")

    def test_normalize_draft_stage_rejects_wrong_stage(self) -> None:
        from backend.generation.study_materials.codex_stages import StageResultError, normalize_stage_result

        with self.assertRaisesRegex(StageResultError, "invalid_stage_result"):
            normalize_stage_result(
                "draft",
                {
                    "stage": "accept",
                    "stage_status": "completed",
                    "stage_version": 1,
                    "payload": {"markdown": "# 错误阶段"},
                },
            )

    def test_normalize_draft_stage_requires_markdown_and_coverage(self) -> None:
        from backend.generation.study_materials.codex_stages import StageResultError, normalize_stage_result

        with self.assertRaisesRegex(StageResultError, "invalid_stage_result"):
            normalize_stage_result(
                "draft",
                {
                    "stage": "draft",
                    "stage_status": "completed",
                    "stage_version": 1,
                    "payload": {"markdown": "# 草稿"},
                },
            )

    async def test_stage_runner_treats_result_as_stage_completion(self) -> None:
        from backend.generation.study_materials import codex_stages

        seen: list[dict] = []
        runtime_calls: list[dict] = []
        options = {
            "preset": "standard",
            "requirements": "保留要求",
            "with_questions": True,
            "with_diagrams": False,
            "enable_extra_tools": True,
            "max_points": 2,
        }

        async def fake_events(**kwargs):
            runtime_calls.append(kwargs)
            yield {"type": "status", "event": "status", "data": {"content": "planning"}}
            yield {
                "type": "result",
                "result": {
                    "stage": "plan",
                    "stage_status": "completed",
                    "stage_version": 1,
                    "payload": {
                        "knowledge_points": [
                            {"id": "kp-1", "title": "增函数", "queries": ["增函数 定义"]},
                        ]
                    },
                },
                "data": {},
            }

        async def sink(event: dict) -> None:
            seen.append(event)

        with patch.object(codex_stages, "run_codex_runtime_agent_events", side_effect=fake_events):
            result = await codex_stages.run_codex_stage(
                stage="plan",
                task_id="task-1",
                user_id="u-1",
                topic="函数单调性",
                subject="高中数学",
                preset="standard",
                options=options,
                payload={},
                event_sink=sink,
            )

        self.assertEqual(result["knowledge_points"][0]["title"], "增函数")
        self.assertEqual([event["type"] for event in seen], ["status"])
        self.assertEqual(runtime_calls[0]["spec"].input_payload["options"], {**options, "workflow_stage": "plan"})
        self.assertIn('"options":', runtime_calls[0]["prompt_override"])
        self.assertIn('"with_questions":true', runtime_calls[0]["prompt_override"])

    async def test_stage_runner_rejects_task_level_done(self) -> None:
        from backend.generation.study_materials import codex_stages

        async def fake_events(**_kwargs):
            yield {"type": "done", "event": "done", "data": {"material": {"markdown": "# 过早完成"}}}

        async def sink(_event: dict) -> None:
            return None

        with patch.object(codex_stages, "run_codex_runtime_agent_events", side_effect=fake_events):
            with self.assertRaisesRegex(codex_stages.StageResultError, "invalid_stage_result"):
                await codex_stages.run_codex_stage(
                    stage="draft",
                    task_id="task-1",
                    user_id="u-1",
                    topic="函数单调性",
                    subject="高中数学",
                    preset="standard",
                    payload={},
                    event_sink=sink,
                )


if __name__ == "__main__":
    unittest.main()
