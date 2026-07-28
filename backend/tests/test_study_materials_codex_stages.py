from __future__ import annotations

import os
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


class StudyMaterialsStagePromptCapTests(unittest.TestCase):
    def _payload(self, *, markdown_chars: int, evidence_per_kp: int) -> dict:
        return {
            "plan": {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]},
            "research": {
                "kp-1": [
                    {
                        "source_class": "web",
                        "url": f"https://example.test/{index}",
                        "title": f"资料 {index}",
                        "snippet": "证" * 800,
                    }
                    for index in range(evidence_per_kp)
                ]
            },
            "markdown": "# 函数单调性\n\n## 增函数\n\n" + ("定义与性质。" * (markdown_chars // 6)),
        }

    def test_revise_prompt_clips_markdown_to_env_budget(self) -> None:
        from backend.generation.study_materials.codex_stages import build_stage_prompt

        with patch.dict(os.environ, {"STUDY_MATERIALS_STAGE_PROMPT_MAX_CHARS": "2000"}):
            prompt = build_stage_prompt(
                stage="revise",
                topic="函数单调性",
                subject="高中数学",
                preset="standard",
                payload=self._payload(markdown_chars=60000, evidence_per_kp=1),
            )

        stage_input = prompt.split("阶段输入：", 1)[1]
        self.assertLessEqual(len(stage_input), 2100)
        self.assertIn("…", stage_input)

    def test_stage_prompt_slims_research_evidence(self) -> None:
        from backend.generation.study_materials.codex_stages import build_stage_prompt

        prompt = build_stage_prompt(
            stage="draft",
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            payload=self._payload(markdown_chars=100, evidence_per_kp=9),
        )

        stage_input = prompt.split("阶段输入：", 1)[1]
        self.assertEqual(stage_input.count("https://example.test/"), 4)
        self.assertNotIn("证" * 600, stage_input)

    def test_stage_prompt_uses_default_budget_without_env(self) -> None:
        from backend.generation.study_materials.codex_stages import build_stage_prompt

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STUDY_MATERIALS_STAGE_PROMPT_MAX_CHARS", None)
            prompt = build_stage_prompt(
                stage="revise",
                topic="函数单调性",
                subject="高中数学",
                preset="standard",
                payload=self._payload(markdown_chars=120000, evidence_per_kp=2),
            )

        stage_input = prompt.split("阶段输入：", 1)[1]
        self.assertLessEqual(len(stage_input), 31000)

    def test_plan_prompt_is_not_capped(self) -> None:
        from backend.generation.study_materials.codex_stages import build_stage_prompt

        with patch.dict(os.environ, {"STUDY_MATERIALS_STAGE_PROMPT_MAX_CHARS": "2000"}):
            prompt = build_stage_prompt(
                stage="plan",
                topic="函数单调性",
                subject="高中数学",
                preset="standard",
                payload={"requirements": "保留要求" * 400},
            )

        self.assertIn("保留要求", prompt)


if __name__ == "__main__":
    unittest.main()
