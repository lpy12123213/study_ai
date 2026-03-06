import unittest

from backend.paper_compose import workflow


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


if __name__ == "__main__":
    unittest.main()

