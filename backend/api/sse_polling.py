from __future__ import annotations

import asyncio
from typing import Any

from backend.core.helpers import get_logger

logger = get_logger(__name__)


def next_poll_delay(current: float, *, had_events: bool, min_s: float = 0.1, max_s: float = 2.0) -> float:
    if had_events:
        return max(float(min_s), 0.01)
    cur = max(float(current or min_s), float(min_s))
    return min(float(max_s), max(float(min_s), cur * 1.6))


async def wait_for_task_event_or_timeout(
    *,
    runtime: Any,
    task_id: str,
    user_id: str,
    last_seq: int,
    timeout_s: float,
) -> bool:
    timeout = max(0.05, float(timeout_s or 0.1))
    task = None
    try:
        task = await runtime.get_task(str(task_id or "").strip())
    except Exception:
        logger.warning("task_event_wait_lookup_failed", extra={"task_id": str(task_id or "")}, exc_info=True)
        task = None

    if task is None or str(getattr(task, "user_id", "") or "") != str(user_id or "").strip():
        await asyncio.sleep(timeout)
        return False
    if str(getattr(task, "status", "") or "") != "running":
        return True

    cond = getattr(task, "cond", None)
    if cond is None:
        await asyncio.sleep(timeout)
        return False

    async with cond:
        try:
            await asyncio.wait_for(
                cond.wait_for(
                    lambda: int(getattr(task, "last_seq", 0) or 0) > int(last_seq or 0)
                    or str(getattr(task, "status", "") or "") != "running"
                ),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            return False
