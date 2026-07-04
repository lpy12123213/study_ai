from __future__ import annotations

import unittest


class StudyMaterialsQualityGateTests(unittest.TestCase):
    def _state(self, *, preset: str = "standard") -> dict:
        from backend.generation.study_materials.quality_gate import draft_hash

        markdown = "# 函数单调性\n\n## 增函数\n\n定义、适用条件、例题、反例与常见误区。"
        return {
            "preset": preset,
            "plan": {
                "knowledge_points": [
                    {"id": "kp-1", "title": "增函数"},
                ]
            },
            "research": {
                "kp-1": [
                    {
                        "source_class": "web",
                        "url": "https://example.test/monotonicity",
                        "title": "函数单调性",
                        "snippet": "增函数的定义和判定方法。",
                    },
                    {
                        "source_class": "wikipedia",
                        "url": "https://zh.wikipedia.org/wiki/单调函数",
                        "title": "单调函数",
                        "snippet": "单调函数及其严格单调形式。",
                    },
                ]
            },
            "markdown": markdown,
            "review": {
                "passed": True,
                "draft_hash": draft_hash(markdown),
                "dimensions": {
                    "定义/概念": {"covered": True},
                    "条件/适用范围": {"covered": True},
                    "应用/题型": {"covered": True},
                    "反例/边界": {"covered": True},
                    "误区/易错点": {"covered": True},
                },
            },
        }

    def test_standard_profile_passes_only_with_current_review_and_two_source_classes(self) -> None:
        from backend.generation.study_materials.quality_gate import evaluate_acceptance

        report = evaluate_acceptance(state=self._state())

        self.assertTrue(report["passed"])
        self.assertEqual(report["failed_checks"], [])
        self.assertTrue(report["per_knowledge_point"]["kp-1"]["passed"])

    def test_missing_research_evidence_blocks_acceptance(self) -> None:
        from backend.generation.study_materials.quality_gate import evaluate_acceptance

        state = self._state()
        state["research"]["kp-1"] = []

        report = evaluate_acceptance(state=state)

        self.assertFalse(report["passed"])
        self.assertIn("research_evidence_missing:kp-1", report["failed_checks"])
        self.assertIn("source_classes_missing:kp-1", report["failed_checks"])

    def test_duplicate_urls_do_not_count_as_distinct_sources(self) -> None:
        from backend.generation.study_materials.quality_gate import evaluate_acceptance

        state = self._state()
        state["research"]["kp-1"] = [
            {
                "source_class": "web",
                "url": "https://example.test/same#part-1",
                "title": "A",
                "snippet": "first",
            },
            {
                "source_class": "wikipedia",
                "url": "https://example.test/same#part-2",
                "title": "B",
                "snippet": "second",
            },
        ]

        report = evaluate_acceptance(state=state)

        self.assertFalse(report["passed"])
        self.assertIn("research_evidence_missing:kp-1", report["failed_checks"])

    def test_review_for_an_older_draft_cannot_pass(self) -> None:
        from backend.generation.study_materials.quality_gate import evaluate_acceptance

        state = self._state()
        state["markdown"] += "\n\n新增但尚未审查的内容。"

        report = evaluate_acceptance(state=state)

        self.assertFalse(report["passed"])
        self.assertIn("review_draft_mismatch", report["failed_checks"])

    def test_archive_acceptance_requires_current_versions_preset_and_hash(self) -> None:
        from backend.generation.study_materials.quality_gate import (
            QUALITY_POLICY_VERSION,
            REVIEW_SCHEMA_VERSION,
            acceptance_record_is_current,
            draft_hash,
        )

        markdown = "# 已验收资料"
        archive = {
            "markdown": markdown,
            "acceptance": {
                "accepted": True,
                "preset": "quick",
                "draft_hash": draft_hash(markdown),
                "quality_policy_version": QUALITY_POLICY_VERSION,
                "review_schema_version": REVIEW_SCHEMA_VERSION,
            },
        }

        self.assertTrue(acceptance_record_is_current(archive=archive, preset="quick", markdown=markdown))

        archive["acceptance"]["quality_policy_version"] = QUALITY_POLICY_VERSION - 1
        self.assertFalse(acceptance_record_is_current(archive=archive, preset="quick", markdown=markdown))
        archive["acceptance"]["quality_policy_version"] = QUALITY_POLICY_VERSION

        self.assertFalse(acceptance_record_is_current(archive=archive, preset="standard", markdown=markdown))
        self.assertFalse(acceptance_record_is_current(archive=archive, preset="quick", markdown=markdown + " changed"))

    def test_archive_acceptance_rejects_changed_content_options(self) -> None:
        from backend.generation.study_materials.quality_gate import (
            acceptance_record_is_current,
            build_acceptance_record,
            draft_hash,
        )

        markdown = "# 函数单调性"
        report = {"passed": True, "draft_hash": draft_hash(markdown), "failed_checks": []}
        archive = {
            "acceptance": build_acceptance_record(
                report=report,
                preset="standard",
                options={"with_questions": False, "with_diagrams": True},
            )
        }

        self.assertTrue(
            acceptance_record_is_current(
                archive=archive,
                preset="standard",
                markdown=markdown,
                options={"with_questions": False, "with_diagrams": True},
            )
        )
        self.assertFalse(
            acceptance_record_is_current(
                archive=archive,
                preset="standard",
                markdown=markdown,
                options={"with_questions": True, "with_diagrams": True},
            )
        )


if __name__ == "__main__":
    unittest.main()
