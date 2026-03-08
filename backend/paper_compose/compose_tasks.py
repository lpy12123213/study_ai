from __future__ import annotations

import os

from backend.paper_compose.task_manager import PaperComposeTaskManager

compose_tasks = PaperComposeTaskManager(
    max_tasks=int(os.getenv("PAPER_COMPOSE_MAX_TASKS") or "50"),
    task_ttl_s=int(os.getenv("PAPER_COMPOSE_TASK_TTL_S") or str(60 * 60)),
    max_events_per_task=int(os.getenv("PAPER_COMPOSE_TASK_MAX_EVENTS") or "6000"),
)
