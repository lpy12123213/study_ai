import unittest

from backend.agent.types import agent_event
from backend.core.logging_utils import set_request_id
from backend.shared.tasks.runtime import TaskRuntime


class TestTraceIds(unittest.TestCase):
    def tearDown(self) -> None:
        set_request_id("")

    def test_agent_event_includes_request_id_as_trace_id(self) -> None:
        set_request_id("rid-123")

        event = agent_event("status", {"content": "ok"})

        self.assertEqual(event["trace_id"], "rid-123")

    def test_task_event_normalization_preserves_trace_id(self) -> None:
        runtime = TaskRuntime.__new__(TaskRuntime)

        event = runtime._normalize_event_payload(
            task_id="task-1",
            event={"type": "progress", "trace_id": "trace-1", "data": {"progress": 10}},
        )

        self.assertEqual(event["trace_id"], "trace-1")
        self.assertNotIn("trace_id", event["data"])


if __name__ == "__main__":
    unittest.main()
