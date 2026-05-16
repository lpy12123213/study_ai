from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any


async def cancel_and_await(task: asyncio.Task[Any] | None) -> None:
    """Cancel a task and wait for it to acknowledge cancellation."""

    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError, RuntimeError):
        await task
