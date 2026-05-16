from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

_semaphore: asyncio.Semaphore | None = None
_semaphore_limit: int | None = None


def _configured_limit() -> int:
    raw = os.getenv("MAX_CONCURRENT_LLM_REQUESTS") or os.getenv("LLM_MAX_CONCURRENT_REQUESTS") or "3"
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 3
    return max(1, min(value, 50))


def get_llm_concurrency_semaphore() -> asyncio.Semaphore:
    global _semaphore, _semaphore_limit
    limit = _configured_limit()
    if _semaphore is None or _semaphore_limit != limit:
        _semaphore = asyncio.Semaphore(limit)
        _semaphore_limit = limit
    return _semaphore


@asynccontextmanager
async def llm_concurrency_slot() -> AsyncIterator[None]:
    sem = get_llm_concurrency_semaphore()
    async with sem:
        yield
