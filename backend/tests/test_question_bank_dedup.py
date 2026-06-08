import unittest

from backend.cli.question_bank.stats.app import find_duplicate_stem_groups


class QuestionBankDedupTests(unittest.TestCase):
    def test_groups_visible_duplicate_fingerprints_with_stable_order(self) -> None:
        rows = [
            {"question_id": "q3", "stem_fingerprint": "fp-b", "stem": "B"},
            {"question_id": "q1", "stem_fingerprint": "fp-a", "stem": "A1"},
            {"question_id": "q2", "stem_fingerprint": "fp-a", "stem": "A2"},
            {"question_id": "q4", "stem_fingerprint": "", "stem": "no fingerprint"},
        ]

        groups = find_duplicate_stem_groups(rows)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["stem_fingerprint"], "fp-a")
        self.assertEqual(groups[0]["question_ids"], ["q1", "q2"])
        self.assertEqual(groups[0]["count"], 2)


if __name__ == "__main__":
    unittest.main()
