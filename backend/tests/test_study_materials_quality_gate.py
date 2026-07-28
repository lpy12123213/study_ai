from __future__ import annotations

import unittest


def _evidence(count: int, *, classes: list[str]) -> list[dict]:
    items = []
    for index in range(count):
        source_class = classes[index % len(classes)]
        items.append(
            {
                "source_class": source_class,
                "url": f"https://example.test/{source_class}/{index}",
                "title": f"资料 {index}",
                "snippet": f"关于知识点的第 {index} 条证据，包含定义与说明。",
            }
        )
    return items


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
            "coverage_map": {"kp-1": True},
            "review": {
                "passed": True,
                "draft_hash": draft_hash(markdown),
                "dimensions": {
                    "增函数": {
                        "present": ["定义/概念", "性质/结论", "条件/适用范围", "反例/边界", "应用/题型"],
                        "missing": [],
                    }
                },
            },
        }

    def _two_point_state(self, *, preset: str) -> dict:
        from backend.generation.study_materials.quality_gate import draft_hash

        markdown = (
            "# 函数单调性\n\n"
            "## 1、增函数\n\n"
            "增函数的定义：设函数 f(x) 的定义域为 I，若对任意 x1<x2 都有 f(x1)<=f(x2)。"
            "其性质、适用条件、反例、误区、例题与推导均充分展开。\n\n"
            "## 2、减函数\n\n"
            "减函数的定义略。"
        )
        return {
            "preset": preset,
            "plan": {
                "knowledge_points": [
                    {"id": "kp-1", "title": "增函数"},
                    {"id": "kp-2", "title": "减函数"},
                ]
            },
            "research": {
                "kp-1": _evidence(4, classes=["web", "wikipedia", "mediawiki"]),
                "kp-2": _evidence(4, classes=["web", "wikipedia", "mediawiki"]),
            },
            "markdown": markdown,
            "coverage_map": {"kp-1": True, "kp-2": True},
            "review": {
                "passed": True,
                "draft_hash": draft_hash(markdown),
                "dimensions": {
                    "增函数": {
                        "present": [
                            "动机/直观",
                            "定义/概念",
                            "性质/结论",
                            "条件/适用范围",
                            "反例/边界",
                            "应用/题型",
                            "推导/证明",
                        ],
                        "missing": [],
                    },
                    "减函数": {
                        "present": ["定义/概念"],
                        "missing": ["性质/结论", "条件/适用范围", "反例/边界", "应用/题型", "推导/证明"],
                    },
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

    def test_kp_title_without_matching_section_fails_visibly(self) -> None:
        from backend.generation.study_materials.quality_gate import draft_hash, evaluate_acceptance

        state = self._state()
        state["markdown"] = "# 函数单调性\n\n## 其他小节\n\n定义、适用条件、例题、反例与常见误区。"
        state["review"]["draft_hash"] = draft_hash(state["markdown"])

        report = evaluate_acceptance(state=state)

        self.assertFalse(report["passed"])
        self.assertIn("draft_section_unmatched:kp-1", report["failed_checks"])
        self.assertNotIn("draft_coverage_missing:kp-1", report["failed_checks"])

    def test_fabricated_all_true_coverage_map_fails_cross_check(self) -> None:
        from backend.generation.study_materials.quality_gate import draft_hash, evaluate_acceptance

        state = self._state()
        # coverage_map 声称已覆盖，但正文没有任何可归属的小节。
        state["markdown"] = "通篇没有任何二级标题的正文。"
        state["review"]["draft_hash"] = draft_hash(state["markdown"])

        report = evaluate_acceptance(state=state)

        self.assertFalse(report["passed"])
        self.assertIn("coverage_map_mismatch:kp-1", report["failed_checks"])
        self.assertIn("draft_section_unmatched:kp-1", report["failed_checks"])

    def test_missing_coverage_map_entry_fails(self) -> None:
        from backend.generation.study_materials.quality_gate import evaluate_acceptance

        state = self._state()
        state["coverage_map"] = {}

        report = evaluate_acceptance(state=state)

        self.assertFalse(report["passed"])
        self.assertIn("coverage_map_mismatch:kp-1", report["failed_checks"])

    def test_per_kp_dimensions_require_definition_and_minimum_count(self) -> None:
        from backend.generation.study_materials.quality_gate import evaluate_acceptance

        state = self._state()
        state["review"]["dimensions"] = {
            "增函数": {"present": ["应用/题型", "反例/边界", "误区/易错点"], "missing": ["定义/概念"]}
        }

        report = evaluate_acceptance(state=state)

        self.assertFalse(report["passed"])
        self.assertIn("kp_dimensions_missing:kp-1", report["failed_checks"])

    def test_one_rich_kp_plus_stub_fails_at_deep_preset(self) -> None:
        from backend.generation.study_materials.quality_gate import evaluate_acceptance

        report = evaluate_acceptance(state=self._two_point_state(preset="deep"))

        self.assertFalse(report["passed"])
        self.assertIn("kp_dimensions_missing:kp-2", report["failed_checks"])
        self.assertTrue(report["per_knowledge_point"]["kp-1"]["passed"])
        self.assertFalse(report["per_knowledge_point"]["kp-2"]["passed"])

    def test_one_rich_kp_plus_stub_fails_at_research_preset(self) -> None:
        from backend.generation.study_materials.quality_gate import evaluate_acceptance

        report = evaluate_acceptance(state=self._two_point_state(preset="research"))

        self.assertFalse(report["passed"])
        self.assertIn("kp_dimensions_missing:kp-2", report["failed_checks"])
        self.assertTrue(report["per_knowledge_point"]["kp-1"]["passed"])

    def test_section_matching_tolerates_numbering_and_punctuation(self) -> None:
        from backend.generation.study_materials.quality_gate import evaluate_acceptance

        state = self._two_point_state(preset="standard")
        # standard 每个知识点至少 3 个维度（min_dimensions-2）；stub 仍应失败但原因不是小节缺失。
        report = evaluate_acceptance(state=state)

        self.assertNotIn("draft_section_unmatched:kp-1", report["failed_checks"])
        self.assertNotIn("draft_section_unmatched:kp-2", report["failed_checks"])

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

    def test_archive_acceptance_max_age_rejects_stale_rows(self) -> None:
        from datetime import datetime, timedelta, timezone

        from backend.generation.study_materials.quality_gate import (
            acceptance_record_is_current,
            build_acceptance_record,
            draft_hash,
        )

        markdown = "# 函数单调性"
        report = {"passed": True, "draft_hash": draft_hash(markdown), "failed_checks": []}
        archive = {
            "acceptance": build_acceptance_record(report=report, preset="standard"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        self.assertTrue(
            acceptance_record_is_current(archive=archive, preset="standard", markdown=markdown, max_age_s=3600)
        )

        archive["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        self.assertFalse(
            acceptance_record_is_current(archive=archive, preset="standard", markdown=markdown, max_age_s=3600)
        )
        # max_age_s 为 None/0 时不做新鲜度检查。
        self.assertTrue(
            acceptance_record_is_current(archive=archive, preset="standard", markdown=markdown, max_age_s=0)
        )
        self.assertTrue(acceptance_record_is_current(archive=archive, preset="standard", markdown=markdown))

    def test_archive_acceptance_max_age_uses_created_at_and_rejects_missing_timestamp(self) -> None:
        from datetime import datetime, timezone

        from backend.generation.study_materials.quality_gate import (
            acceptance_record_is_current,
            build_acceptance_record,
            draft_hash,
        )

        markdown = "# 函数单调性"
        report = {"passed": True, "draft_hash": draft_hash(markdown), "failed_checks": []}
        archive = {
            "acceptance": build_acceptance_record(report=report, preset="standard"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        self.assertTrue(
            acceptance_record_is_current(archive=archive, preset="standard", markdown=markdown, max_age_s=600)
        )

        del archive["created_at"]
        self.assertFalse(
            acceptance_record_is_current(archive=archive, preset="standard", markdown=markdown, max_age_s=600)
        )


if __name__ == "__main__":
    unittest.main()
