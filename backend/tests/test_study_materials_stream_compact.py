"""SSE 追赶压缩：落后事件超过阈值时折叠瞬态/快照类事件（thinking/status/text_delta 等）。

线上问题：退出页面后重连，全量回放数千条 thinking/text_delta 事件导致恢复极慢。
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.generation.study_materials import orchestrator as orch


def _evt(seq: int, etype: str, data: dict | None = None) -> dict:
    return {"taskId": "t1", "seq": seq, "type": etype, "data": data or {}}


class StreamCompactTests(unittest.IsolatedAsyncioTestCase):
    async def _collect(self, events, task_row, after_seq=0):
        async def fake_list_events(*, user_id, task_id, after_seq=0, limit=200, session=None):  # noqa: A002
            return [e for e in events if e["seq"] > after_seq][:limit]

        with patch.object(orch, "db_get_task", new=AsyncMock(return_value=task_row)), patch.object(
            orch, "db_list_task_events", new=AsyncMock(side_effect=fake_list_events)
        ):
            mgr = orch.StudyMaterialsTaskManager()
            return [e async for e in mgr.stream("t1", user_id="u1", after_seq=after_seq)]

    async def test_catchup_compaction_over_threshold(self) -> None:
        events = [_evt(1, "task_started", {"query": "q"})]
        events += [_evt(i, "thinking", {"content": f"t{i}"}) for i in range(2, 1002)]
        events += [_evt(i, "tool_result", {"tool": "web_search_knowledge", "success": True}) for i in range(1002, 1012)]
        events += [_evt(i, "text_delta", {"content": f"# v{i}"}) for i in range(1012, 1017)]
        events.append(_evt(1017, "workflow_stage", {"stage": "review"}))
        task_row = {"id": "t1", "user_id": "u1", "status": "completed", "last_seq": 1017}

        got = await self._collect(events, task_row)
        types = [e["type"] for e in got]

        # 瞬态/快照折叠为各自最新一条；有 catch_up 标记且计数正确。
        self.assertEqual(types.count("thinking"), 1)
        self.assertEqual(types.count("text_delta"), 1)
        self.assertEqual(got[0]["type"], "catch_up")
        self.assertEqual(got[0]["data"]["skipped"], 1017 - 14)
        # 状态演进类全量保留。
        self.assertEqual(types.count("tool_result"), 10)
        self.assertEqual(types.count("task_started"), 1)
        self.assertEqual(types.count("workflow_stage"), 1)
        # 保留的 text_delta 是最新快照；整体顺序保持。
        td = next(e for e in got if e["type"] == "text_delta")
        self.assertEqual(td["data"]["content"], "# v1016")
        self.assertEqual(got[-1]["type"], "workflow_stage")

    async def test_below_threshold_no_compaction(self) -> None:
        events = [_evt(i, "thinking", {"content": str(i)}) for i in range(1, 50)]
        task_row = {"id": "t1", "user_id": "u1", "status": "completed", "last_seq": 49}

        got = await self._collect(events, task_row)
        types = [e["type"] for e in got]
        self.assertEqual(types.count("thinking"), 49)
        self.assertNotIn("catch_up", types)


if __name__ == "__main__":
    unittest.main()
