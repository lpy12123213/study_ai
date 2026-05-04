from __future__ import annotations

import os

from backend.shared.tasks.db_store import DbTaskStore
from backend.shared.tasks.runtime import TaskRuntime


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


task_runtime = TaskRuntime(
    store=DbTaskStore(),
    max_tasks=_env_int("TASK_RUNTIME_MAX_TASKS", 200),
    task_ttl_s=_env_int("TASK_RUNTIME_TTL_S", 60 * 60),
    max_events_per_task=_env_int("TASK_RUNTIME_MAX_EVENTS", 8000),
    task_event_flush_interval_ms=_env_int("TASK_EVENT_FLUSH_INTERVAL_MS", 500),
    task_event_batch_size=_env_int("TASK_EVENT_BATCH_SIZE", 50),
)
