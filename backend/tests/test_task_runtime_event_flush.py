from __future__ import annotations

import unittest
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.shared.tasks.runtime import RuntimeTask, TaskRuntime
from backend.shared.tasks.store import TaskEventWrite


class FakeTaskStore:
    def __init__(self) -> None:
        self.batches: List[List[TaskEventWrite]] = []
        self.status_updates: List[str] = []
        self.order: List[str] = []

    async def upsert_task(self, **kwargs: Any) -> dict:
        return {}

    async def update_task_status(
        self,
        *,
        user_id: str,
        task_id: str,
        status: str,
        progress: Optional[float] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
    ) -> bool:
        self.status_updates.append(status)
        self.order.append(f"status:{status}")
        return True

    async def append_task_event(self, **kwargs: Any) -> int:
        raise AssertionError("runtime should use append_task_events for persistence")

    async def append_task_events(self, *, user_id: str, task_id: str, events: List[TaskEventWrite]) -> int:
        batch = list(events)
        self.batches.append(batch)
        self.order.append(f"append:{len(batch)}")
        return max(int(evt.seq or 0) for evt in batch)

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


def make_task() -> RuntimeTask:
    return RuntimeTask(task_id="task-1", user_id="user-1", task_type="unit", title="Unit task")


class TaskRuntimeEventFlushTests(unittest.IsolatedAsyncioTestCase):
    async def test_append_event_flushes_in_batches_at_batch_size(self) -> None:
        store = FakeTaskStore()
        runtime = TaskRuntime(
            store=store,
            task_event_flush_interval_ms=60_000,
            task_event_batch_size=3,
        )
        task = make_task()

        await runtime.append_event(task, {"type": "progress", "data": {"progress": 10}})
        await runtime.append_event(task, {"type": "progress", "data": {"progress": 20}})

        self.assertEqual(store.batches, [])
        self.assertEqual(len(task.pending_persist_events), 2)

        await runtime.append_event(task, {"type": "step", "step": {"id": "done", "status": "completed"}})

        self.assertEqual(len(store.batches), 1)
        self.assertEqual([evt.seq for evt in store.batches[0]], [1, 2, 3])
        self.assertEqual([evt.event_type for evt in store.batches[0]], ["progress", "progress", "step"])
        self.assertEqual(task.pending_persist_events, [])

    async def test_complete_task_forces_pending_flush_before_status_update(self) -> None:
        store = FakeTaskStore()
        runtime = TaskRuntime(
            store=store,
            task_event_flush_interval_ms=60_000,
            task_event_batch_size=50,
        )
        task = make_task()

        await runtime.append_event(task, {"type": "progress", "data": {"progress": 25}})
        self.assertEqual(store.batches, [])

        await runtime.complete_task(task, result={"ok": True})

        self.assertEqual(store.order, ["append:1", "status:completed"])
        self.assertEqual([evt.seq for evt in store.batches[0]], [1])
        self.assertEqual(store.status_updates, ["completed"])
        self.assertEqual(task.pending_persist_events, [])


if __name__ == "__main__":
    unittest.main()
