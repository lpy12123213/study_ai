from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol


@dataclass(frozen=True)
class TaskTerminalUpdate:
    status: str
    ended_at: datetime
    progress: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class TaskStore(Protocol):
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
    ) -> dict: ...

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
    ) -> bool: ...

    async def append_task_event(
        self,
        *,
        user_id: str,
        task_id: str,
        event_type: str,
        payload: Dict[str, Any],
        seq: Optional[int] = None,
        progress: Optional[float] = None,
    ) -> int: ...

    async def get_task(
        self,
        *,
        user_id: str,
        task_id: str,
        include_events: bool = False,
        events_limit: int = 500,
    ) -> Optional[dict]: ...

    async def list_task_events(
        self,
        *,
        user_id: str,
        task_id: str,
        after_seq: int = 0,
        limit: int = 2000,
    ) -> List[dict]: ...

    async def list_tasks(
        self,
        *,
        user_id: str,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]: ...

    async def average_duration_seconds(
        self,
        *,
        user_id: str,
        task_type: str,
        sample: int = 50,
    ) -> Optional[float]: ...

    async def fail_running_tasks_on_startup(
        self,
        *,
        reason: str = "server_restarted",
        limit: int = 5000,
    ) -> int: ...

