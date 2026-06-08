import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.migrations import sync_migrate_db_schema
from backend.database.repositories.content import wrongbook as wrongbook_repo
from backend.database.repositories.question import question_cache as cache_repo
from backend.database.schema import Base, WrongQuestion


class WrongbookSrsMigrationTests(unittest.TestCase):
    def test_sync_migration_adds_srs_columns_and_review_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(f"sqlite:///{temp_dir}/wrongbook-migration.db", future=True)
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql(
                        "CREATE TABLE wrong_questions ("
                        "id INTEGER PRIMARY KEY,"
                        "user_id VARCHAR(64) NOT NULL DEFAULT '',"
                        "question_id VARCHAR(50) NOT NULL"
                        ")"
                    )

                    sync_migrate_db_schema(conn)

                    columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(wrong_questions)").fetchall()}
                    indexes = {row[1] for row in conn.exec_driver_sql("PRAGMA index_list(wrong_questions)").fetchall()}
            finally:
                engine.dispose()

            self.assertTrue(
                {
                    "ease_factor",
                    "interval_days",
                    "repetitions",
                    "next_review_at",
                    "last_reviewed_at",
                }.issubset(columns)
            )
            self.assertIn("ix_wrong_questions_next_review", indexes)
            self.assertIn("ix_wrong_questions_user_next_review", indexes)


class WrongbookSrsRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/wrongbook-srs.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.patches = [
            patch.object(wrongbook_repo, "async_session_maker", self.session_maker),
            patch.object(cache_repo, "async_session_maker", self.session_maker),
        ]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_new_wrong_question_is_due_immediately_and_queue_is_enriched(self) -> None:
        now = datetime(2026, 1, 1, 9, 0)
        await cache_repo.upsert_question_cache(
            [
                {
                    "question_id": "q-due",
                    "subject": "高中数学",
                    "knowledge_point": "函数",
                    "stem": "设函数 f(x)=x^2。",
                    "answer": "略",
                    "analysis": "配方法。",
                }
            ]
        )

        item = await wrongbook_repo.upsert_wrong_question(
            user_id="user-a",
            question_id="q-due",
            subject="高中数学",
            knowledge_point="函数",
            mastery=30,
            note="二次函数顶点忘了",
            now=now,
        )

        self.assertEqual(item["ease_factor"], 2.5)
        self.assertEqual(item["interval_days"], 0)
        self.assertEqual(item["repetitions"], 0)
        self.assertTrue(item["next_review_at"])

        due = await wrongbook_repo.list_due_reviews(user_id="user-a", now=now)

        self.assertEqual([row["question_id"] for row in due], ["q-due"])
        self.assertEqual(due[0]["question"]["stem"], "设函数 f(x)=x^2。")
        self.assertEqual(due[0]["question"]["answer"], "略")

    async def test_record_review_updates_mastery_and_removes_item_from_due_queue(self) -> None:
        now = datetime(2026, 1, 1, 9, 0)
        await wrongbook_repo.upsert_wrong_question(
            user_id="user-a",
            question_id="q-review",
            subject="高中数学",
            knowledge_point="函数",
            mastery=30,
            now=now,
        )

        reviewed = await wrongbook_repo.record_review(
            user_id="user-a",
            question_id="q-review",
            rating="good",
            now=now,
        )

        self.assertEqual(reviewed["mastery"], 45)
        self.assertEqual(reviewed["interval_days"], 1)
        self.assertEqual(reviewed["repetitions"], 1)
        self.assertEqual(datetime.fromisoformat(reviewed["next_review_at"]), now + timedelta(days=1))
        self.assertEqual(datetime.fromisoformat(reviewed["last_reviewed_at"]), now)

        due = await wrongbook_repo.list_due_reviews(user_id="user-a", now=now)
        self.assertEqual(due, [])

    async def test_aggregate_mastery_by_knowledge_point_counts_due_items(self) -> None:
        now = datetime(2026, 1, 1, 9, 0)
        await wrongbook_repo.upsert_wrong_question(
            user_id="user-a",
            question_id="q-weak",
            subject="高中数学",
            knowledge_point="函数",
            mastery=20,
            now=now,
        )
        await wrongbook_repo.upsert_wrong_question(
            user_id="user-a",
            question_id="q-strong",
            subject="高中数学",
            knowledge_point="函数",
            mastery=80,
            now=now,
        )
        await wrongbook_repo.upsert_wrong_question(
            user_id="user-a",
            question_id="q-future",
            subject="高中数学",
            knowledge_point="几何",
            mastery=70,
            now=now,
        )
        async with self.session_maker() as session:
            row = (
                await session.execute(
                    select(WrongQuestion).where(
                        WrongQuestion.user_id == "user-a",
                        WrongQuestion.question_id == "q-future",
                    )
                )
            ).scalar_one()
            row.next_review_at = now + timedelta(days=2)
            session.add(row)
            await session.commit()

        result = await wrongbook_repo.aggregate_mastery_by_knowledge_point(user_id="user-a", subject="高中数学", now=now)

        points = {row["knowledge_point"]: row for row in result["knowledge_points"]}
        self.assertEqual(points["函数"]["count"], 2)
        self.assertEqual(points["函数"]["avg_mastery"], 50.0)
        self.assertEqual(points["函数"]["min_mastery"], 20)
        self.assertEqual(points["函数"]["due_count"], 2)
        self.assertEqual(points["几何"]["due_count"], 0)
        self.assertEqual(result["subjects"][0]["subject"], "高中数学")
        self.assertEqual(result["subjects"][0]["count"], 3)


if __name__ == "__main__":
    unittest.main()
