"""全量 trace 分页端点：GET /api/study-materials/tasks/{id}/trace（不压缩）。

实时 SSE 追赶通道继续压缩瞬态事件保流畅；本端点供前端过程面板拉取完整历史，
note_write/todo_update/figure_trace/section_fill 等结构化事件永不折叠。
"""

from __future__ import annotations

import contextlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.api.auth import require_auth
from backend.app import create_app
from backend.generation.study_materials import orchestrator as orch

_TRACE_TASK_ID = "sm-trace"
_TRACE_EVENT_COUNT = 920


def _trace_events(task_id: str = _TRACE_TASK_ID, count: int = _TRACE_EVENT_COUNT) -> list[dict]:
    return [
        {
            "taskId": task_id,
            "seq": i,
            "type": "thinking_delta",
            "agent_path": "root/author",
            "data": {"content": f"chunk-{i}"},
        }
        for i in range(1, count + 1)
    ]


class StudyMaterialsTraceApiTests(unittest.TestCase):
    def _override_auth(self, app) -> None:
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}

    def _make_client(self, events: list[dict], *, task_id: str = _TRACE_TASK_ID) -> TestClient:
        """真实跑 orchestrator.get_events_after 分页逻辑，仅替换 DB 访问与 API 层任务视图。"""

        app = create_app()
        self._override_auth(app)

        async def fake_list_events(*, user_id, task_id, after_seq=0, limit=200, session=None):  # noqa: A002
            return [e for e in events if e["seq"] > after_seq][:limit]

        task_row = {"id": task_id, "user_id": "u-1", "status": "completed", "last_seq": len(events)}
        task_view = SimpleNamespace(task_id=task_id, user_id="u-1", status="completed")

        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("backend.api.study_materials._tasks.get_task", new=AsyncMock(return_value=task_view)))
        stack.enter_context(patch.object(orch, "db_get_task", new=AsyncMock(return_value=task_row)))
        stack.enter_context(patch.object(orch, "db_list_task_events", new=AsyncMock(side_effect=fake_list_events)))
        return TestClient(app)

    def test_trace_paginates_full_history_without_compaction(self) -> None:
        client = self._make_client(_trace_events())

        first = client.get(f"/api/study-materials/tasks/{_TRACE_TASK_ID}/trace", params={"after_seq": 0, "limit": 500})
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertEqual(set(body.keys()), {"events", "next_after_seq", "has_more"})
        self.assertEqual(len(body["events"]), 500)
        self.assertTrue(body["has_more"])
        self.assertIsInstance(body["next_after_seq"], int)

        second = client.get(
            f"/api/study-materials/tasks/{_TRACE_TASK_ID}/trace",
            params={"after_seq": body["next_after_seq"], "limit": 500},
        )
        self.assertEqual(second.status_code, 200)
        body2 = second.json()
        self.assertEqual(len(body2["events"]), _TRACE_EVENT_COUNT - 500)
        self.assertFalse(body2["has_more"])

        seen = first.json()["events"] + body2["events"]
        self.assertEqual(len(seen), _TRACE_EVENT_COUNT)
        self.assertEqual([e["seq"] for e in seen], list(range(1, _TRACE_EVENT_COUNT + 1)))
        for evt in seen:
            self.assertEqual(evt["agent_path"], "root/author")

    def test_trace_unknown_task_404(self) -> None:
        app = create_app()
        self._override_auth(app)
        with patch("backend.api.study_materials._tasks.get_task", new=AsyncMock(return_value=None)):
            client = TestClient(app)
            resp = client.get("/api/study-materials/tasks/no-such-task/trace")
        self.assertEqual(resp.status_code, 404)

    def test_trace_limit_defaults_to_500(self) -> None:
        client = self._make_client(_trace_events())
        resp = client.get(f"/api/study-materials/tasks/{_TRACE_TASK_ID}/trace")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["events"]), 500)
        self.assertTrue(body["has_more"])

    def test_trace_limit_clamped_to_500(self) -> None:
        client = self._make_client(_trace_events())
        resp = client.get(f"/api/study-materials/tasks/{_TRACE_TASK_ID}/trace", params={"limit": 9999})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["events"]), 500)
        self.assertTrue(body["has_more"])

    def test_trace_limit_floor_is_1(self) -> None:
        client = self._make_client(_trace_events())
        resp = client.get(f"/api/study-materials/tasks/{_TRACE_TASK_ID}/trace", params={"limit": 0})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["events"]), 1)
        self.assertTrue(body["has_more"])


class StreamCatchupRegressionTests(unittest.IsolatedAsyncioTestCase):
    """现有 stream 追赶行为保持压缩（不回归）：落后 >800 条时 thinking_delta 折叠为最新一条。"""

    async def _collect(self, events, task_row, after_seq=0):
        async def fake_list_events(*, user_id, task_id, after_seq=0, limit=200, session=None):  # noqa: A002
            return [e for e in events if e["seq"] > after_seq][:limit]

        with patch.object(orch, "db_get_task", new=AsyncMock(return_value=task_row)), patch.object(
            orch, "db_list_task_events", new=AsyncMock(side_effect=fake_list_events)
        ):
            mgr = orch.StudyMaterialsTaskManager()
            return [e async for e in mgr.stream("t1", user_id="u1", after_seq=after_seq)]

    async def test_catchup_still_compacts_thinking_delta(self) -> None:
        events = [{"taskId": "t1", "seq": 1, "type": "task_started", "agent_path": "root", "data": {"query": "q"}}]
        events += _trace_events(task_id="t1", count=900)
        for i, evt in enumerate(events[1:], start=2):
            evt["seq"] = i
        events.append({"taskId": "t1", "seq": 902, "type": "done", "data": {}})
        task_row = {"id": "t1", "user_id": "u1", "status": "completed", "last_seq": 902}

        got = await self._collect(events, task_row)
        types = [e["type"] for e in got]

        self.assertEqual(types.count("thinking_delta"), 1)
        self.assertEqual(got[0]["type"], "catch_up")
        td = next(e for e in got if e["type"] == "thinking_delta")
        self.assertEqual(td["data"]["content"], "chunk-900")
        self.assertEqual(td["agent_path"], "root/author")


class CompactionWhitelistTests(unittest.TestCase):
    """note_write/todo_update/figure_trace/section_fill 永不折叠。"""

    def test_structured_trace_events_never_folded(self) -> None:
        types = ["note_write", "todo_update", "figure_trace", "section_fill"]
        events = [{"seq": i, "type": types[i % 4], "data": {}} for i in range(1, 41)]
        kept, skipped = orch._compact_catchup_events(events)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(kept), 40)

    def test_whitelist_wins_even_if_type_marked_latest_only(self) -> None:
        events = [{"seq": i, "type": "note_write", "data": {"name": f"n{i}"}} for i in range(1, 6)]
        tainted = set(orch._CATCHUP_LATEST_ONLY_TYPES) | {"note_write"}
        with patch.object(orch, "_CATCHUP_LATEST_ONLY_TYPES", new=frozenset(tainted)):
            kept, skipped = orch._compact_catchup_events(events)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(kept), 5)


class TraceTtlSettingTests(unittest.TestCase):
    def test_trace_ttl_defaults_to_zero(self) -> None:
        with patch.dict(os.environ, {"STUDY_MATERIALS_TRACE_TTL_S": ""}):
            self.assertEqual(orch.study_materials_trace_ttl_s(), 0.0)

    def test_trace_ttl_reads_env(self) -> None:
        with patch.dict(os.environ, {"STUDY_MATERIALS_TRACE_TTL_S": "3600"}):
            self.assertEqual(orch.study_materials_trace_ttl_s(), 3600.0)

    def test_trace_ttl_invalid_env_falls_back_to_zero(self) -> None:
        with patch.dict(os.environ, {"STUDY_MATERIALS_TRACE_TTL_S": "abc"}):
            self.assertEqual(orch.study_materials_trace_ttl_s(), 0.0)


if __name__ == "__main__":
    unittest.main()
