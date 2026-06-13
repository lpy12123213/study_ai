from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.migrations import sync_migrate_db_schema
from backend.database.repositories.system import tasks as tasks_repo
from backend.database.schema import Base, Task


class TaskDurationAggregateRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/tasks.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.session_patch = patch.object(tasks_repo, "async_session_maker", self.session_maker)
        self.session_patch.start()

    async def asyncTearDown(self) -> None:
        self.session_patch.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def _insert_task(
        self,
        *,
        task_id: str,
        user_id: str,
        task_type: str,
        status: str,
        started_at: datetime | None,
        ended_at: datetime | None,
    ) -> None:
        async with self.session_maker() as session:
            session.add(
                Task(
                    id=task_id,
                    user_id=user_id,
                    task_type=task_type,
                    title=task_id,
                    status=status,
                    progress=1.0 if status == "completed" else 0.0,
                    last_seq=0,
                    request_json="{}",
                    result_json="{}",
                    error_json="{}",
                    started_at=started_at,
                    ended_at=ended_at,
                )
            )
            await session.commit()

    async def _list_aggregates(self) -> list[object]:
        async with self.session_maker() as session:
            result = await session.execute(select(tasks_repo.TaskDurationAggregate))
            return list(result.scalars().all())

    async def test_update_task_status_updates_aggregate_once_when_task_completes(self) -> None:
        started_at = datetime(2026, 1, 1, 12, 0, 0)
        first_ended_at = started_at + timedelta(seconds=30)
        second_ended_at = started_at + timedelta(seconds=45)

        await tasks_repo.upsert_task(
            user_id="user-1",
            task_id="task-1",
            task_type="question_library.generate",
            title="Generate questions",
            status="running",
            started_at=started_at,
        )

        self.assertTrue(
            await tasks_repo.update_task_status(
                user_id="user-1",
                task_id="task-1",
                status="failed",
                ended_at=first_ended_at,
            )
        )
        self.assertEqual(await self._list_aggregates(), [])

        self.assertTrue(
            await tasks_repo.update_task_status(
                user_id="user-1",
                task_id="task-1",
                status="completed",
                ended_at=first_ended_at,
            )
        )

        await tasks_repo.update_task_status(
            user_id="user-1",
            task_id="task-1",
            status="completed",
            ended_at=second_ended_at,
        )

        rows = await self._list_aggregates()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.task_type, "question_library.generate")
        self.assertEqual(row.completed_count, 1)
        self.assertEqual(row.duration_sum_seconds, 30.0)
        self.assertEqual(row.last_duration_seconds, 30.0)
        self.assertGreaterEqual(row.duration_ema_seconds, 30.0)
        self.assertLessEqual(row.duration_ema_seconds, 30.0)

    async def test_rebuild_task_duration_aggregates_is_idempotent_and_recovers_partial_state(self) -> None:
        empty_count = await tasks_repo.rebuild_task_duration_aggregates()
        self.assertEqual(empty_count, 0)
        self.assertEqual(await self._list_aggregates(), [])

        started_at = datetime(2026, 1, 1, 12, 0, 0)
        await self._insert_task(
            task_id="task-a1",
            user_id="user-1",
            task_type="study_materials",
            status="completed",
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=20),
        )
        await self._insert_task(
            task_id="task-a2",
            user_id="user-1",
            task_type="study_materials",
            status="completed",
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=40),
        )
        await self._insert_task(
            task_id="task-b1",
            user_id="user-2",
            task_type="study_materials",
            status="running",
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=999),
        )
        await self._insert_task(
            task_id="task-c1",
            user_id="user-1",
            task_type="question_library.generate",
            status="completed",
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=10),
        )
        await self._insert_task(
            task_id="task-c2",
            user_id="user-1",
            task_type="question_library.generate",
            status="canceled",
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=50),
        )
        await self._insert_task(
            task_id="task-c3",
            user_id="user-1",
            task_type="question_library.generate",
            status="completed",
            started_at=started_at,
            ended_at=None,
        )

        rebuilt = await tasks_repo.rebuild_task_duration_aggregates()
        self.assertEqual(rebuilt, 2)

        rows = await self._list_aggregates()
        self.assertEqual(sorted(row.task_type for row in rows), ["question_library.generate", "study_materials"])

        study_row = next(row for row in rows if row.task_type == "study_materials")
        self.assertEqual(study_row.completed_count, 2)
        self.assertEqual(study_row.duration_sum_seconds, 60.0)
        self.assertEqual(study_row.last_duration_seconds, 40.0)
        self.assertGreater(study_row.duration_ema_seconds, 20.0)
        self.assertLess(study_row.duration_ema_seconds, 40.0)

        async with self.session_maker() as session:
            await session.execute(
                tasks_repo.TaskDurationAggregate.__table__.update()
                .where(tasks_repo.TaskDurationAggregate.task_type == "study_materials")
                .values(completed_count=999, duration_sum_seconds=999.0, duration_ema_seconds=999.0, last_duration_seconds=999.0)
            )
            await session.commit()

        rebuilt_again = await tasks_repo.rebuild_task_duration_aggregates()
        self.assertEqual(rebuilt_again, 2)

        rows = await self._list_aggregates()
        study_row = next(row for row in rows if row.task_type == "study_materials")
        self.assertEqual(study_row.completed_count, 2)
        self.assertEqual(study_row.duration_sum_seconds, 60.0)
        self.assertEqual(study_row.last_duration_seconds, 40.0)

    async def test_average_duration_seconds_uses_only_requesting_users_history(self) -> None:
        started_at = datetime(2026, 1, 1, 12, 0, 0)

        await tasks_repo.upsert_task(
            user_id="user-a",
            task_id="task-a1",
            task_type="study_materials",
            title="User A task",
            status="running",
            started_at=started_at,
        )
        await tasks_repo.update_task_status(
            user_id="user-a",
            task_id="task-a1",
            status="completed",
            ended_at=started_at + timedelta(seconds=600),
        )

        self.assertIsNone(await tasks_repo.average_duration_seconds(user_id="user-b", task_type="study_materials"))


class TaskDurationAggregateMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/migrations.db"
        self.engine = create_engine(f"sqlite:///{db_path}", future=True)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_sync_migrate_db_schema_creates_duration_aggregate_table_and_index_idempotently(self) -> None:
        with self.engine.begin() as conn:
            sync_migrate_db_schema(conn)
            sync_migrate_db_schema(conn)

            table_name = conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='task_duration_aggregates'"
            ).scalar_one_or_none()
            index_name = conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_task_duration_aggregates_updated_at'"
            ).scalar_one_or_none()

        self.assertEqual(table_name, "task_duration_aggregates")
        self.assertEqual(index_name, "ix_task_duration_aggregates_updated_at")

    def test_sync_migrate_db_schema_ensures_task_event_indexes(self) -> None:
        with self.engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE task_events ("
                "id INTEGER PRIMARY KEY,"
                "task_id VARCHAR(64) NOT NULL,"
                "seq INTEGER NOT NULL,"
                "event_type VARCHAR(50),"
                "payload_json TEXT,"
                "created_at DATETIME"
                ")"
            )
            sync_migrate_db_schema(conn)

            indexes = {
                row[1]
                for row in conn.exec_driver_sql("PRAGMA index_list(task_events)").fetchall()
                if len(row) > 1
            }

        self.assertIn("ix_task_events_task_id", indexes)
        self.assertIn("ix_task_events_task_id_seq", indexes)
