import unittest

from backend.generation.paper_compose import auto_planner, workflow
from backend.llm.prompts import create_default_prompt_registry


class TestPaperComposeWorkflowUtils(unittest.TestCase):
    def test_difficulty_from_slot(self):
        self.assertEqual(workflow._difficulty_from_slot("easy"), "简单")
        self.assertEqual(workflow._difficulty_from_slot("medium"), "中等")
        self.assertEqual(workflow._difficulty_from_slot("hard"), "困难")
        self.assertEqual(workflow._difficulty_from_slot("简单"), "简单")
        self.assertEqual(workflow._difficulty_from_slot(""), "中等")

    def test_stem_fingerprint_is_stable(self):
        fp1 = workflow._stem_fingerprint("  Hello  World ")
        fp2 = workflow._stem_fingerprint("hello\nworld")
        self.assertEqual(fp1, fp2)
        self.assertEqual(len(fp1), 32)

    def test_normalize_question_type_alias(self):
        available = [{"id": "1", "name": "解答题"}, {"id": "2", "name": "填空题"}, {"id": "3", "name": "选择题"}]
        self.assertEqual(workflow._normalize_question_type("简答题", available), "解答题")
        self.assertEqual(workflow._normalize_question_type("单选题", available), "选择题")

    def test_paper_compose_planner_prompts_use_registry(self):
        registry = create_default_prompt_registry()

        self.assertEqual(
            auto_planner._structure_planner_system_prompt(),
            registry.render("paper_compose.structure_planner.v1").content,
        )
        self.assertEqual(
            workflow._question_match_reviewer_system_prompt(),
            registry.render("paper_compose.question_match_reviewer.v1").content,
        )

    def test_auto_review_rejected_questions_are_filtered_before_save(self):
        slot_results = [
            {
                "selected": [
                    {"question_id": "bad", "review_action": "reject", "stem": "bad"},
                    {"question_id": "ok", "stem": "ok"},
                ],
                "candidates": [{"question_id": "replacement", "stem": "replacement"}],
            }
        ]

        summary = workflow._filter_or_replace_rejected_questions(slot_results)

        self.assertEqual(summary["rejected"], 1)
        self.assertEqual(summary["replaced"], 1)
        self.assertEqual([q["question_id"] for q in slot_results[0]["selected"]], ["replacement", "ok"])

    def test_build_save_question_dicts_adds_text_lint_flags(self):
        q_dicts = workflow._build_save_question_dicts(
            [
                {
                    "question_id": "q1",
                    "stem": "含未替换 {var}",
                    "answer": "$x",
                    "quality_flags": ["existing"],
                }
            ],
            subject="高中数学",
        )

        flags = q_dicts[0]["quality_flags"]
        self.assertIn("existing", flags)
        self.assertIn("unresolved_placeholder", flags)
        self.assertIn("unbalanced_inline_math", flags)


if __name__ == "__main__":
    unittest.main()
