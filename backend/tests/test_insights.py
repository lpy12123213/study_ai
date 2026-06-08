from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.api.auth import require_auth
from backend.api.insights import router as insights_router
from backend.database.repositories.analytics import insights as insights_repo
from backend.database.schema import (
    Base,
    EssayEvaluation,
    ExamResult,
    ExamSession,
    LearningPlan,
    LearningPlanItem,
    Paper,
    StudentAnswer,
    WrongQuestion,
)


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _naive(value: str) -> datetime:
    return datetime.fromisoformat(value)


class InsightsRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def _seed_learning_rows(self) -> None:
        async with self.session_maker() as session:
            session.add(Paper(id=1, user_id="user-a", paper_name="函数小测"))
            session.add(
                ExamSession(
                    id="exam-1",
                    user_id="user-a",
                    paper_id=1,
                    paper_name="函数小测",
                    status="submitted",
                    submitted_at=_naive("2026-06-07T10:00:00"),
                    total_score=24,
                    max_score=30,
                )
            )
            session.add(
                ExamResult(
                    session_id="exam-1",
                    user_id="user-a",
                    total_score=24,
                    max_score=30,
                    score_ratio=0.8,
                    objective_correct=2,
                    objective_total=3,
                    subjective_score=8,
                    subjective_max=10,
                )
            )
            session.add_all(
                [
                    StudentAnswer(
                        session_id="exam-1",
                        user_id="user-a",
                        question_id="q1",
                        question_type="single_choice",
                        is_correct=1,
                        score=5,
                        max_score=5,
                    ),
                    StudentAnswer(
                        session_id="exam-1",
                        user_id="user-a",
                        question_id="q2",
                        question_type="single_choice",
                        is_correct=0,
                        score=0,
                        max_score=5,
                    ),
                    StudentAnswer(
                        session_id="exam-1",
                        user_id="user-a",
                        question_id="q3",
                        question_type="calculation",
                        is_correct=1,
                        score=8,
                        max_score=10,
                    ),
                ]
            )
            session.add_all(
                [
                    WrongQuestion(
                        user_id="user-a",
                        question_id="w1",
                        subject="数学",
                        knowledge_point="导数",
                        mastery=20,
                        updated_at=_naive("2026-06-07T12:00:00"),
                    ),
                    WrongQuestion(
                        user_id="user-a",
                        question_id="w2",
                        subject="数学",
                        knowledge_point="函数",
                        mastery=70,
                        updated_at=_naive("2026-06-08T12:00:00"),
                    ),
                    WrongQuestion(
                        user_id="user-a",
                        question_id="w3",
                        subject="英语",
                        knowledge_point="阅读",
                        mastery=10,
                        updated_at=_naive("2026-06-08T12:00:00"),
                    ),
                ]
            )
            session.add(
                EssayEvaluation(
                    user_id="user-a",
                    subject="语文",
                    essay_type="argumentative",
                    essay_text="作文正文",
                    score_total=45,
                    score_max=60,
                    created_at=_naive("2026-06-08T09:00:00"),
                )
            )
            plan = LearningPlan(user_id="user-a", title="六月复习")
            session.add(plan)
            await session.flush()
            session.add_all(
                [
                    LearningPlanItem(
                        plan_id=plan.id,
                        title="复盘函数",
                        completed=1,
                        completed_at=_naive("2026-06-08T18:00:00"),
                    ),
                    LearningPlanItem(
                        plan_id=plan.id,
                        title="整理错题",
                        completed=0,
                        due_at=_naive("2026-06-07T23:00:00"),
                    ),
                ]
            )
            await session.commit()

    async def test_empty_overview_returns_stable_zero_structure(self) -> None:
        async with self.session_maker() as session:
            overview = await insights_repo.get_insights_overview(
                session,
                user_id="empty-user",
                dt_from=_utc("2026-06-01T00:00:00"),
                dt_to=_utc("2026-06-08T23:59:59"),
            )

        self.assertEqual(overview["exams"]["total_sessions"], 0)
        self.assertEqual(overview["exams"]["trend"], [])
        self.assertEqual(overview["exams"]["objective"], {"correct": 0, "total": 0, "ratio": 0.0})
        self.assertEqual(overview["wrongbook"]["total"], 0)
        self.assertEqual([row["count"] for row in overview["wrongbook"]["mastery_distribution"]], [0, 0, 0, 0])
        self.assertEqual(overview["activity"]["active_days"], 0)
        self.assertEqual(overview["activity"]["plan_completion"], {"completed": 0, "total": 0, "overdue": 0, "ratio": 0.0})

    async def test_overview_aggregates_learning_data_for_user_window(self) -> None:
        await self._seed_learning_rows()

        async with self.session_maker() as session:
            overview = await insights_repo.get_insights_overview(
                session,
                user_id="user-a",
                dt_from=_utc("2026-06-06T00:00:00"),
                dt_to=_utc("2026-06-08T23:59:59"),
            )

        self.assertEqual(overview["exams"]["trend"], [{"date": "2026-06-07", "score_ratio": 0.8, "count": 1}])
        self.assertEqual(overview["exams"]["objective"], {"correct": 2, "total": 3, "ratio": 0.6667})
        self.assertEqual(overview["exams"]["subjective"], {"score": 8.0, "max_score": 10.0, "ratio": 0.8})
        self.assertIn(
            {"question_type": "single_choice", "correct": 1, "total": 2, "ratio": 0.5},
            overview["exams"]["accuracy_by_type"],
        )
        self.assertEqual(overview["essays"]["trend"], [{"date": "2026-06-08", "score_ratio": 0.75, "count": 1}])
        self.assertEqual([row["count"] for row in overview["wrongbook"]["mastery_distribution"]], [2, 0, 1, 0])
        self.assertEqual(overview["wrongbook"]["weak_points"][0]["knowledge_point"], "阅读")
        self.assertEqual(overview["activity"]["active_days"], 2)
        self.assertEqual(overview["activity"]["current_streak"], 2)
        self.assertEqual(overview["activity"]["plan_completion"], {"completed": 1, "total": 2, "overdue": 1, "ratio": 0.5})

    async def test_subject_filter_applies_to_wrongbook_and_essays_only(self) -> None:
        await self._seed_learning_rows()

        async with self.session_maker() as session:
            overview = await insights_repo.get_insights_overview(
                session,
                user_id="user-a",
                dt_from=_utc("2026-06-06T00:00:00"),
                dt_to=_utc("2026-06-08T23:59:59"),
                subject="数学",
            )

        self.assertEqual(overview["exams"]["total_sessions"], 1)
        self.assertEqual(overview["essays"]["trend"], [])
        self.assertEqual(overview["wrongbook"]["total"], 2)
        self.assertEqual(overview["wrongbook"]["weak_points"][0]["knowledge_point"], "导数")


class InsightsApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with self.session_maker() as session:
            session.add(Paper(id=1, user_id="user-a", paper_name="函数小测"))
            session.add(
                ExamSession(
                    id="exam-1",
                    user_id="user-a",
                    paper_id=1,
                    paper_name="函数小测",
                    status="submitted",
                    submitted_at=_naive("2026-06-07T10:00:00"),
                )
            )
            session.add(ExamResult(session_id="exam-1", user_id="user-a", score_ratio=0.8))
            await session.commit()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    def _client(self) -> TestClient:
        from backend.api import insights as insights_api

        app = FastAPI()
        app.include_router(insights_router)
        app.dependency_overrides[require_auth] = lambda: {"user_id": "user-a", "username": "alice"}
        self.addCleanup(app.dependency_overrides.clear)
        session_patch = patch.object(insights_api, "async_session_maker", self.session_maker)
        session_patch.start()
        self.addCleanup(session_patch.stop)
        return TestClient(app)

    def test_overview_endpoint_uses_auth_user(self) -> None:
        client = self._client()

        response = client.get("/insights/overview?from=2026-06-06T00:00:00Z&to=2026-06-08T23:59:59Z")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["exams"]["total_sessions"], 1)
        self.assertEqual(payload["exams"]["recent"][0]["session_id"], "exam-1")

    def test_export_endpoint_returns_flat_csv(self) -> None:
        client = self._client()

        response = client.get("/insights/export?from=2026-06-06T00:00:00Z&to=2026-06-08T23:59:59Z")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("insights-", response.headers["content-disposition"])
        self.assertIn("metric,value", response.text)
        self.assertIn("exams.total_sessions,1", response.text)
