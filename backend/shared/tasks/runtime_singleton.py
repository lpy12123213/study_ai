from __future__ import annotations

from backend.core.settings import env_int
from backend.shared.tasks.db_store import DbTaskStore
from backend.shared.tasks.runtime import TaskRuntime

task_runtime = TaskRuntime(
    store=DbTaskStore(),
    max_tasks=env_int("TASK_RUNTIME_MAX_TASKS", 200),
    task_ttl_s=env_int("TASK_RUNTIME_TTL_S", 60 * 60),
    max_events_per_task=env_int("TASK_RUNTIME_MAX_EVENTS", 8000),
    task_event_flush_interval_ms=env_int("TASK_EVENT_FLUSH_INTERVAL_MS", 500),
    task_event_batch_size=env_int("TASK_EVENT_BATCH_SIZE", 50),
)
