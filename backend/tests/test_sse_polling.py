import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.api.sse_polling import next_poll_delay, wait_for_task_event_or_timeout


class FakeRuntime:
    def __init__(self, task=None):
        self.task = task

    async def get_task(self, task_id: str):
        return self.task


class SsePollingTest(unittest.TestCase):
    def test_next_poll_delay_backs_off_and_resets_after_events(self):
        self.assertEqual(next_poll_delay(0.1, had_events=True), 0.1)
        self.assertGreater(next_poll_delay(0.1, had_events=False), 0.1)
        self.assertLessEqual(next_poll_delay(2.0, had_events=False), 2.0)

    def test_wait_for_task_event_returns_when_runtime_task_advances(self):
        async def run():
            cond = asyncio.Condition()
            task = SimpleNamespace(user_id="u1", status="running", last_seq=1, cond=cond)

            async def notify():
                await asyncio.sleep(0.01)
                async with cond:
                    task.last_seq = 2
                    cond.notify_all()

            notifier = asyncio.create_task(notify())
            try:
                changed = await wait_for_task_event_or_timeout(
                    runtime=FakeRuntime(task),
                    task_id="t1",
                    user_id="u1",
                    last_seq=1,
                    timeout_s=0.2,
                )
            finally:
                await notifier
            return changed

        self.assertTrue(asyncio.run(run()))

    def test_wait_for_task_event_times_out_without_runtime_task(self):
        async def run():
            return await wait_for_task_event_or_timeout(
                runtime=FakeRuntime(None),
                task_id="missing",
                user_id="u1",
                last_seq=0,
                timeout_s=0.05,
            )

        self.assertFalse(asyncio.run(run()))

    def test_backend_sse_streams_do_not_use_fixed_half_second_polling(self):
        root = Path(__file__).resolve().parents[2]
        paths = [
            root / "backend" / "api" / "tasks.py",
            root / "backend" / "api" / "question_library.py",
        ]
        offenders = []
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Await):
                    continue
                call = node.value
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                is_asyncio_sleep = (
                    isinstance(func, ast.Attribute)
                    and func.attr == "sleep"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "asyncio"
                )
                if not is_asyncio_sleep or not call.args:
                    continue
                arg = call.args[0]
                is_half_second = isinstance(arg, ast.Constant) and arg.value == 0.5
                if is_half_second:
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")

        self.assertEqual(offenders, [], f"fixed polling sleeps remain: {offenders}")


if __name__ == "__main__":
    unittest.main()
