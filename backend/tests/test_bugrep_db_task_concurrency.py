from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.repositories.question import question_library as lib_repo
from backend.database.repositories.system import item_meta as item_meta_repo
from backend.database.repositories.system import misc as misc_repo
from backend.database.repositories.system import tasks as tasks_repo
from backend.database.schema import Base, QuestionLibraryItem, TaskEvent, UserItemMeta
from backend.shared.tasks.runtime import RuntimeTask, TaskRuntime
from backend.shared.tasks.store import TaskEventWrite


class BugrepDbTaskConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "bugrep.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.patches = [
            patch.object(lib_repo, "async_session_maker", self.session_maker),
            patch.object(item_meta_repo, "async_session_maker", self.session_maker),
            patch.object(misc_repo, "async_session_maker", self.session_maker),
            patch.object(tasks_repo, "async_session_maker", self.session_maker),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_question_library_concurrent_upsert_keeps_one_row(self) -> None:
        async def write(subject: str) -> None:
            await lib_repo.upsert_question_library_items(
                user_id="user-a",
                items=[{"question_id": "q-race", "subject": subject, "origin": "crawled"}],
            )

        await asyncio.gather(write("数学"), write("物理"))

        async with self.session_maker() as session:
            rows = (
                await session.execute(
                    select(QuestionLibraryItem).where(
                        QuestionLibraryItem.user_id == "user-a",
                        QuestionLibraryItem.question_id == "q-race",
                    )
                )
            ).scalars().all()
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0].subject, {"数学", "物理"})

    async def test_item_meta_concurrent_upsert_keeps_one_row_for_both_modules(self) -> None:
        long_uid = " user-" + ("x" * 100)

        await asyncio.gather(
            item_meta_repo.upsert_item_meta(
                user_id=long_uid,
                item_type="question",
                item_id="q1",
                starred=True,
                tags=["a"],
            ),
            misc_repo.upsert_item_meta(
                user_id=long_uid,
                item_type="question",
                item_id="q1",
                pinned=True,
                tags=["b"],
            ),
        )

        async with self.session_maker() as session:
            rows = (await session.execute(select(UserItemMeta))).scalars().all()
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(len(rows[0].user_id), 64)
        self.assertNotEqual(rows[0].user_id, str(long_uid).strip()[:64])

    async def test_append_task_events_concurrent_auto_seq_is_unique(self) -> None:
        await tasks_repo.upsert_task(
            user_id="user-a",
            task_id="task-race",
            task_type="unit",
            title="Unit",
            status="running",
        )

        async def append(name: str) -> int:
            return await tasks_repo.append_task_events(
                user_id="user-a",
                task_id="task-race",
                events=[
                    {"event_type": "progress", "payload": {"name": name, "i": 1}},
                    {"event_type": "progress", "payload": {"name": name, "i": 2}},
                ],
            )

        await asyncio.gather(append("a"), append("b"))

        async with self.session_maker() as session:
            rows = (
                await session.execute(select(TaskEvent).where(TaskEvent.task_id == "task-race").order_by(TaskEvent.seq))
            ).scalars().all()
            task = await tasks_repo.get_task(user_id="user-a", task_id="task-race", session=session)

        self.assertEqual([row.seq for row in rows], [1, 2, 3, 4])
        self.assertEqual(task["last_seq"], 4)


class SlowUpsertStore:
    def __init__(self, release: asyncio.Event) -> None:
        self.release = release
        self.status_updates: List[str] = []
        self.runner_started = asyncio.Event()

    async def upsert_task(self, **kwargs: Any) -> dict:
        await self.release.wait()
        return {}

    async def update_task_status(self, **kwargs: Any) -> bool:
        self.status_updates.append(str(kwargs.get("status") or ""))
        return True

    async def append_task_events(self, *, user_id: str, task_id: str, events: List[TaskEventWrite]) -> int:
        return max((int(evt.seq or 0) for evt in events), default=0)

    async def append_task_event(self, **kwargs: Any) -> int:
        return 0

    async def get_task(self, **kwargs: Any) -> Optional[dict]:
        return None

    async def list_task_events(self, **kwargs: Any) -> List[dict]:
        return []

    async def list_tasks(self, **kwargs: Any) -> List[dict]:
        return []

    async def average_duration_seconds(self, **kwargs: Any) -> Optional[float]:
        return None

    async def fail_running_tasks_on_startup(self, **kwargs: Any) -> int:
        return 0


class BugrepRuntimeRaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_during_create_does_not_start_runner_after_cancel(self) -> None:
        release = asyncio.Event()
        store = SlowUpsertStore(release)
        runtime = TaskRuntime(store=store)

        async def runner(task: RuntimeTask) -> None:
            store.runner_started.set()

        create = asyncio.create_task(
            runtime.create_task(
                task_id="task-race",
                user_id="user-a",
                task_type="unit",
                title="Unit",
                request={},
                runner_factory=runner,
            )
        )
        while await runtime.get_task("task-race") is None:
            await asyncio.sleep(0)

        canceled = await runtime.cancel_task(task_id="task-race", user_id="user-a", reason="user_cancel")
        release.set()
        task = await create
        await asyncio.sleep(0.01)

        self.assertTrue(canceled)
        self.assertEqual(task.status, "canceled")
        self.assertIsNone(task.runner)
        self.assertFalse(store.runner_started.is_set())


if __name__ == "__main__":
    unittest.main()
