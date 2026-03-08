import unittest


class TestQuestionLibraryGenerate(unittest.TestCase):
    def test_build_ai_question_id(self) -> None:
        from backend.question_library.generation import build_ai_question_id

        qid = build_ai_question_id(now_ts=0, suffix="a1b2c3d4")
        self.assertTrue(qid.startswith("ai_"))
        self.assertLessEqual(len(qid), 50)
