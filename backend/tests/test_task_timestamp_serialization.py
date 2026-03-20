import unittest
from datetime import datetime

from backend.database.schema import Task, TaskEvent
from backend.database.repositories.tasks import _event_to_dict, _task_to_dict


class TaskTimestampSerializationTests(unittest.TestCase):
    def test_task_to_dict_emits_utc_timezone_suffix(self) -> None:
        dt = datetime(2026, 3, 14, 11, 0, 0, 123456)  # naive UTC in this codebase
        task = Task(
            id="task-1",
            user_id="user-1",
            task_type="demo",
            title="Demo",
            status="running",
            progress=0.0,
            last_seq=0,
            request_json="{}",
            result_json="{}",
            error_json="{}",
            created_at=dt,
            updated_at=dt,
            started_at=dt,
            ended_at=dt,
        )

        out = _task_to_dict(task)
        self.assertTrue(str(out.get("created_at") or "").endswith("Z"))
        self.assertTrue(str(out.get("updated_at") or "").endswith("Z"))
        self.assertTrue(str(out.get("started_at") or "").endswith("Z"))
        self.assertTrue(str(out.get("ended_at") or "").endswith("Z"))

    def test_event_to_dict_emits_utc_timezone_suffix(self) -> None:
        dt = datetime(2026, 3, 14, 11, 0, 1, 0)
        evt = TaskEvent(
            task_id="task-1",
            seq=1,
            event_type="ping",
            payload_json="{}",
            created_at=dt,
        )

        out = _event_to_dict(evt)
        self.assertTrue(str(out.get("created_at") or "").endswith("Z"))

