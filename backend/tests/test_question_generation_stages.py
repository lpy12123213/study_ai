from __future__ import annotations

import unittest


class QuestionGenerationStagesTests(unittest.TestCase):
    def test_catalog_keeps_generation_flow_in_stable_order(self) -> None:
        from backend.generation.question_library.stages import QUESTION_GENERATION_STAGES

        stage_ids = [stage.stage_id for stage in QUESTION_GENERATION_STAGES]

        self.assertEqual(
            stage_ids,
            [
                "source_pack",
                "reference_crawl",
                "reference_analysis",
                "brainstorm",
                "spec_search",
                "draft_realization",
                "diagram_generation",
                "judge",
                "final_selection",
                "pending_review",
            ],
        )
        self.assertEqual(QUESTION_GENERATION_STAGES[0].group, "prepare")
        self.assertEqual(QUESTION_GENERATION_STAGES[-1].group, "review")

    def test_stage_progress_payload_includes_structured_flow_metadata(self) -> None:
        from backend.generation.question_library.stages import build_stage_progress_payload

        payload = build_stage_progress_payload(
            "judge",
            progress=84.0,
            stats={"evaluated": 6, "accepted": 3, "rejected": 3},
            sample={"stem_preview": "已知函数..."},
        )

        self.assertEqual(payload["stage_id"], "judge")
        self.assertEqual(payload["stage_label"], "判题筛选")
        self.assertEqual(payload["stage_group"], "quality")
        self.assertEqual(payload["stage_order"], 8)
        self.assertEqual(payload["progress"], 84.0)
        self.assertIn("description", payload)
        self.assertIn("summary", payload)
        self.assertIn("evaluated=6", payload["summary"])
        self.assertEqual(payload["stats"]["accepted"], 3)
        self.assertEqual(payload["sample"]["stem_preview"], "已知函数...")


if __name__ == "__main__":
    unittest.main()
