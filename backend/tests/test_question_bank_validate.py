import unittest

from backend.cli.question_bank.validate.app import detect_item_issues


class QuestionBankValidateRuleTests(unittest.TestCase):
    def test_detects_missing_content_low_quality_flags_and_placeholders(self) -> None:
        item = {
            "question_id": "q1",
            "has_answer": False,
            "has_analysis": False,
            "quality_score": 95,
        }
        cache_row = {
            "stem": "已知 [公式:abc123]，求解。",
            "answer": "",
            "analysis": "",
            "quality_score": 42,
            "quality_flags": "broken_formula",
        }

        issues = detect_item_issues(item, cache_row, min_quality=60)

        self.assertEqual(
            [issue.code for issue in issues],
            ["missing_answer", "missing_analysis", "low_quality", "quality_flags", "bad_markup"],
        )
        self.assertEqual(issues[2].detail, "quality_score=42 < 60")

    def test_uses_cache_answer_and_analysis_when_list_flags_are_stale(self) -> None:
        item = {
            "question_id": "q2",
            "has_answer": False,
            "has_analysis": False,
            "quality_score": 80,
        }
        cache_row = {
            "stem": "正常题干",
            "answer": "A",
            "analysis": "因为如此",
            "quality_score": 80,
            "quality_flags": "",
        }

        self.assertEqual(detect_item_issues(item, cache_row, min_quality=60), [])


if __name__ == "__main__":
    unittest.main()
