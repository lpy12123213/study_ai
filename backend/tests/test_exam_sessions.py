from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.repositories.exam import exam_sessions as exam_repo
from backend.database.repositories.question import papers as papers_repo
from backend.database.schema import Base
from backend.generation.exam_grading.objective import grade_objective_answer
from backend.generation.exam_grading.orchestrator import grade_exam_session
from backend.llm.prompts import create_default_prompt_registry


class ObjectiveGradingTests(unittest.TestCase):
    def test_grades_single_multi_and_fill_blank_answers(self) -> None:
        single = grade_objective_answer(
            question_type="single_choice",
            expected_answer="B",
            answer_data={"selected_options": ["b"]},
            max_score=5,
        )
        multi = grade_objective_answer(
            question_type="multi_choice",
            expected_answer="A,C",
            answer_data={"selected_options": ["c", "A"]},
            max_score=6,
        )
        fill = grade_objective_answer(
            question_type="fill_blank",
            expected_answer="牛顿 或 Newton",
            answer_data={"fill_blank_text": " newton "},
            max_score=4,
        )

        self.assertEqual(single["score"], 5)
        self.assertTrue(single["is_correct"])
        self.assertEqual(multi["score"], 6)
        self.assertTrue(multi["is_correct"])
        self.assertEqual(fill["score"], 4)
        self.assertTrue(fill["is_correct"])

    def test_fill_blank_repeated_slots_require_each_submitted_slot(self) -> None:
        full = grade_objective_answer(
            question_type="fill_blank",
            expected_answer="2；2",
            answer_data={"fill_blank_text": "2；2"},
            max_score=4,
        )
        partial = grade_objective_answer(
            question_type="fill_blank",
            expected_answer="2；2",
            answer_data={"fill_blank_text": "2"},
            max_score=4,
        )
        wrong_short = grade_objective_answer(
            question_type="fill_blank",
            expected_answer="2；3",
            answer_data={"fill_blank_text": "2"},
            max_score=4,
        )

        self.assertTrue(full["is_correct"])
        self.assertEqual(full["score"], 4)
        self.assertFalse(partial["is_correct"])
        self.assertEqual(partial["score"], 0)
        self.assertFalse(wrong_short["is_correct"])
        self.assertEqual(wrong_short["score"], 0)


class SubjectiveGradingPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_subjective_grading_system_prompt_uses_registry(self) -> None:
        from backend.generation.exam_grading import subjective

        captured = {}

        async def fake_chat_completion_text(**kwargs):  # type: ignore[no-untyped-def]
            captured["messages"] = kwargs["messages"]
            return '{"score":3,"max_score":5,"reasoning":"步骤基本正确","strengths":["有思路"],"weaknesses":["缺少结论"]}'

        with patch.object(subjective, "is_llm_configured", return_value=True), patch.object(
            subjective,
            "LESSON_PLAN_MODEL",
            "dummy-model",
        ), patch.object(subjective, "chat_completion_text", new=fake_chat_completion_text):
            result = await subjective.grade_subjective_answer(
                question={"stem": "证明函数单调性", "answer": "略", "analysis": "略"},
                answer_data={"text_answer": "先求导再判断符号。"},
                max_score=5,
            )

        self.assertEqual(
            captured["messages"][0]["content"],
            create_default_prompt_registry().render("exam.subjective.grade.v1").content,
        )
        self.assertEqual(result["score"], 3.0)
        self.assertEqual(result["grading_json"]["mode"], "llm")


class ExamSessionRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.patches = [
            patch.object(papers_repo, "async_session_maker", self.session_maker),
            patch.object(exam_repo, "async_session_maker", self.session_maker),
        ]
        for p in self.patches:
            p.start()

        self.paper_id = await papers_repo.save_paper(
            user_id="user-a",
            paper_name="函数小测",
            questions=[
                {
                    "question_id": "q-single",
                    "type": "single_choice",
                    "stem": "1+1=?",
                    "answer": "B",
                    "analysis": "2",
                },
                {
                    "question_id": "q-fill",
                    "type": "fill_blank",
                    "stem": "力的单位是?",
                    "answer": "N 或 牛顿",
                    "analysis": "国际单位制。",
                },
            ],
        )

    async def asyncTearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_session_hides_answers_and_enforces_user_scope(self) -> None:
        created = await exam_repo.create_exam_session(
            user_id="user-a",
            paper_id=self.paper_id,
            mode="timed",
            time_limit_minutes=45,
        )

        session = await exam_repo.get_exam_session(user_id="user-a", session_id=created["session_id"])
        other = await exam_repo.get_exam_session(user_id="user-b", session_id=created["session_id"])

        self.assertIsNotNone(session)
        self.assertIsNone(other)
        self.assertEqual(session["paper_name"], "函数小测")
        self.assertEqual(session["status"], "in_progress")
        self.assertEqual(len(session["questions"]), 2)
        self.assertEqual(session["questions"][0]["stem"], "1+1=?")
        self.assertNotIn("answer", session["questions"][0])
        self.assertIsNotNone(session["expires_at"])

    async def test_saves_answers_and_submit_creates_result(self) -> None:
        created = await exam_repo.create_exam_session(
            user_id="user-a",
            paper_id=self.paper_id,
            mode="untimed",
            time_limit_minutes=None,
        )
        session_id = created["session_id"]

        await exam_repo.save_answer(
            user_id="user-a",
            session_id=session_id,
            question_id="q-single",
            answer_data={"selected_options": ["B"], "question_type": "single_choice"},
        )
        await exam_repo.save_answer(
            user_id="user-a",
            session_id=session_id,
            question_id="q-fill",
            answer_data={"fill_blank_text": "牛顿", "question_type": "fill_blank"},
        )

        result = await grade_exam_session(user_id="user-a", session_id=session_id)
        loaded = await exam_repo.get_exam_result(user_id="user-a", session_id=session_id)
        submitted = await exam_repo.get_exam_session(user_id="user-a", session_id=session_id, include_answers=True)

        self.assertEqual(result["total_score"], result["max_score"])
        self.assertEqual(result["objective_correct"], 2)
        self.assertEqual(loaded["session_id"], session_id)
        self.assertEqual(submitted["status"], "submitted")
        self.assertIsNotNone(datetime.fromisoformat(str(submitted["submitted_at"])))


if __name__ == "__main__":
    unittest.main()
