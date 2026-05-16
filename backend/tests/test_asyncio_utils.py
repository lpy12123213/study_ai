import asyncio
import unittest


class AsyncioUtilsTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_and_await_finishes_pending_task(self) -> None:
        from backend.core.asyncio_utils import cancel_and_await

        started = asyncio.Event()

        async def worker():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(worker())
        await started.wait()
        await cancel_and_await(task)

        self.assertTrue(task.cancelled())


if __name__ == "__main__":
    unittest.main()
