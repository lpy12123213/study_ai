from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.database.repositories.system.tasks import (
    append_task_event as db_append_task_event,
    average_duration_seconds as db_average_duration_seconds,
    fail_running_tasks_on_startup as db_fail_running_tasks_on_startup,
    get_task as db_get_task,
    list_task_events as db_list_task_events,
    list_tasks as db_list_tasks,
    update_task_status as db_update_task_status,
    upsert_task as db_upsert_task,
)
from backend.shared.tasks.store import TaskStore


class DbTaskStore(TaskStore):
    async def upsert_task(
        self,
        *,
        user_id: str,
        task_id: str,
        task_type: str,
        title: str,
        status: str,
        progress: float,
        request: Optional[Dict[str, Any]] = None,
        parent_task_id: Optional[str] = None,
        started_at: Optional[datetime] = None,
    ) -> dict:
        return await db_upsert_task(
            user_id=user_id,
            task_id=task_id,
            task_type=task_type,
            title=title,
            status=status,
            progress=progress,
            request=request,
            parent_task_id=parent_task_id,
            started_at=started_at,
        )

    async def update_task_status(
        self,
        *,
        user_id: str,
        task_id: str,
        status: str,
        progress: Optional[float] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
    ) -> bool:
        return await db_update_task_status(
            user_id=user_id,
            task_id=task_id,
            status=status,
            progress=progress,
            result=result,
            error=error,
            started_at=started_at,
            ended_at=ended_at,
        )

    async def append_task_event(
        self,
        *,
        user_id: str,
        task_id: str,
        event_type: str,
        payload: Dict[str, Any],
        seq: Optional[int] = None,
        progress: Optional[float] = None,
    ) -> int:
        return await db_append_task_event(
            user_id=user_id,
            task_id=task_id,
            event_type=event_type,
            payload=payload,
            seq=seq,
            progress=progress,
        )

    async def get_task(
        self,
        *,
        user_id: str,
        task_id: str,
        include_events: bool = False,
        events_limit: int = 500,
    ) -> Optional[dict]:
        return await db_get_task(user_id=user_id, task_id=task_id, include_events=include_events, events_limit=events_limit)

    async def list_task_events(
        self,
        *,
        user_id: str,
        task_id: str,
        after_seq: int = 0,
        limit: int = 2000,
    ) -> List[dict]:
        return await db_list_task_events(user_id=user_id, task_id=task_id, after_seq=after_seq, limit=limit)

    async def list_tasks(
        self,
        *,
        user_id: str,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        return await db_list_tasks(user_id=user_id, status=status, task_type=task_type, limit=limit, offset=offset)

    async def average_duration_seconds(
        self,
        *,
        user_id: str,
        task_type: str,
        sample: int = 50,
    ) -> Optional[float]:
        return await db_average_duration_seconds(user_id=user_id, task_type=task_type, sample=sample)

    async def fail_running_tasks_on_startup(
        self,
        *,
        reason: str = "server_restarted",
        limit: int = 5000,
    ) -> int:
        return await db_fail_running_tasks_on_startup(reason=reason, limit=limit)
