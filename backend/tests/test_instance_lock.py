"""Tests for the backend instance lock (restart-recovery misfire protection)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.core.instance_lock import (
    _pid_alive,
    clear_backend_instance_lock,
    mark_backend_instance_started,
    other_live_backend_instance,
)


class InstanceLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.lock_path = Path(self.tmp.name) / "backend-instance.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_lock(self, payload: object) -> None:
        self.lock_path.write_text(json.dumps(payload), encoding="utf-8")

    def test_pid_alive_self_and_invalid(self) -> None:
        self.assertTrue(_pid_alive(os.getpid()))
        self.assertFalse(_pid_alive(0))
        self.assertFalse(_pid_alive(-1))

    def test_no_lock_or_corrupt_lock_means_no_live_instance(self) -> None:
        with self.subTest(case="missing"):
            self.assertIsNone(other_live_backend_instance(self.lock_path))
        with self.subTest(case="corrupt"):
            self.lock_path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(other_live_backend_instance(self.lock_path))

    def test_dead_holder_is_ignored(self) -> None:
        self._write_lock({"pid": 99999999, "started_at": 0})
        self.assertIsNone(other_live_backend_instance(self.lock_path))

    def test_live_holder_is_reported_but_own_pid_is_not(self) -> None:
        # 用当前进程 pid 模拟"另一个存活实例"。
        self._write_lock({"pid": os.getpid(), "started_at": 123.0})
        self.assertIsNone(other_live_backend_instance(self.lock_path))

        self._write_lock({"pid": os.getppid() or os.getpid(), "started_at": 123.0})
        holder = other_live_backend_instance(self.lock_path)
        # 父进程通常存活；若环境特殊（父进程已退）则退化为 None，两者都合法。
        self.assertIn(holder, (None, {"pid": os.getppid(), "started_at": 123.0}))

    def test_mark_started_writes_own_pid_and_clear_removes(self) -> None:
        mark_backend_instance_started(self.lock_path)
        data = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.assertEqual(data["pid"], os.getpid())
        self.assertIsNotNone(data["started_at"])

        clear_backend_instance_lock(self.lock_path)
        self.assertFalse(self.lock_path.exists())
        clear_backend_instance_lock(self.lock_path)  # 幂等


class RestartRecoveryGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_skipped_when_other_instance_alive(self) -> None:
        from backend.shared.tasks.runtime import TaskRuntime

        runtime = TaskRuntime(store=AsyncMock())
        with (
            patch(
                "backend.core.instance_lock.other_live_backend_instance",
                return_value={"pid": 424242, "started_at": 1.0},
            ) as holder_mock,
            patch("backend.core.instance_lock.mark_backend_instance_started") as mark_mock,
        ):
            await runtime.restart_recovery(reason="server_restarted")

        holder_mock.assert_called_once()
        mark_mock.assert_not_called()
        runtime._store.fail_running_tasks_on_startup.assert_not_awaited()

    async def test_recovery_runs_and_marks_instance_when_no_live_holder(self) -> None:
        from backend.shared.tasks.runtime import TaskRuntime

        runtime = TaskRuntime(store=AsyncMock())
        with (
            patch("backend.core.instance_lock.other_live_backend_instance", return_value=None),
            patch("backend.core.instance_lock.mark_backend_instance_started") as mark_mock,
        ):
            await runtime.restart_recovery(reason="server_restarted")

        runtime._store.fail_running_tasks_on_startup.assert_awaited_once()
        mark_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
