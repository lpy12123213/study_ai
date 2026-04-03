from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.time_utils import utcnow_naive
from backend.database.repositories.tasks import (
    append_task_event as db_append_task_event,
    update_task_status as db_update_task_status,
)

logger = get_logger(__name__)


def _now_s() -> float:
    return time.time()


@dataclass
class QuestionLibraryTask:
    task_id: str
    user_id: str
    kind: str  # crawl|generate|score
    request: Dict[str, Any]
    created_at_s: float = field(default_factory=_now_s)
    updated_at_s: float = field(default_factory=_now_s)
    status: str = "running"  # running|completed|failed
    error: Optional[str] = None
    progress: float = 0.0

    # seq starts at 1; `events[i-1]["seq"] == i`.
    events: List[Dict[str, Any]] = field(default_factory=list)
    last_seq: int = 0
    seq_offset: int = 0  # number of dropped events; first stored seq is seq_offset + 1

    # Latest step snapshot (for status endpoint).
    steps_by_id: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Notified when events/status change.
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)

    # Runner task (created by manager).
    runner: Optional[asyncio.Task] = None


class QuestionLibraryTaskManager:
    """In-memory question-library task manager with SSE replay support."""

    def __init__(
        self,
        *,
        max_tasks: int = 50,
        task_ttl_s: int = 60 * 60,
        max_events_per_task: int = 5000,
    ) -> None:
        self._tasks: Dict[str, QuestionLibraryTask] = {}
        self._lock = asyncio.Lock()
        self._max_tasks = max(1, int(max_tasks))
        self._task_ttl_s = max(60, int(task_ttl_s))
        self._max_events_per_task = max(200, int(max_events_per_task))

    async def create_task(
        self,
        *,
        task_id: str,
        user_id: str,
        kind: str,
        request: Dict[str, Any],
        runner_factory,
    ) -> QuestionLibraryTask:
        tid = (task_id or "").strip()
        if not tid:
            raise ValueError("missing_task_id")
        uid = (user_id or "").strip() or "anonymous"
        kind_v = (kind or "").strip() or "unknown"
        req = request if isinstance(request, dict) else {}

        async with self._lock:
            self._gc_locked()

            existing = self._tasks.get(tid)
            if existing is not None:
                if existing.user_id != uid:
                    raise ValueError("task_id_conflict")
                if existing.runner and not existing.runner.done():
                    existing.runner.cancel()
                self._tasks.pop(tid, None)

            if len(self._tasks) >= self._max_tasks:
                self._drop_oldest_locked()

            task = QuestionLibraryTask(task_id=tid, user_id=uid, kind=kind_v, request=dict(req))
            self._tasks[tid] = task

        # A starter event helps the frontend render immediately.
        await self._append_event(
            task,
            {
                "type": "step",
                "step": {
                    "id": "task_started",
                    "title": f"开始任务：{kind_v}",
                    "status": "running",
                    "startTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "toolName": f"question_library_{kind_v}",
                    "input": {"taskId": tid},
                },
            },
        )

        task.runner = asyncio.create_task(runner_factory(task))
        return task

    async def get_task(self, task_id: str) -> Optional[QuestionLibraryTask]:
        tid = (task_id or "").strip()
        if not tid:
            return None
        async with self._lock:
            self._gc_locked()
            return self._tasks.get(tid)

    async def stream(self, task_id: str, *, after_seq: int = 0, heartbeat_s: float = 4.0) -> AsyncIterator[dict]:
        tid = (task_id or "").strip()
        if not tid:
            return

        last_sent_seq = max(0, int(after_seq or 0))

        while True:
            task = await self.get_task(tid)
            if not task:
                return

            # If client asks for a sequence that is too old, tell them to restart.
            first_seq = task.seq_offset + 1
            if last_sent_seq < first_seq - 1:
                yield {
                    "taskId": tid,
                    "type": "error",
                    "seq": task.last_seq,
                    "data": {
                        "error": "Event backlog truncated; please restart.",
                        "first_seq": first_seq,
                        "last_seq": task.last_seq,
                    },
                }
                last_sent_seq = first_seq - 1

            start_idx = max(0, last_sent_seq - task.seq_offset)
            batch = task.events[start_idx:]
            for evt in batch:
                seq = int(evt.get("seq") or 0)
                if seq <= last_sent_seq:
                    continue
                last_sent_seq = seq
                yield evt

            if task.status != "running":
                return

            async with task.cond:
                try:
                    await asyncio.wait_for(
                        task.cond.wait_for(lambda: task.last_seq > last_sent_seq or task.status != "running"),
                        timeout=max(0.5, float(heartbeat_s or 4.0)),
                    )
                except asyncio.TimeoutError:
                    yield {
                        "taskId": tid,
                        "type": "progress",
                        "data": {"progress": float(task.progress or 0.0)},
                    }

    async def status_payload(self, *, task_id: str, user_id: str) -> Optional[dict]:
        tid = (task_id or "").strip()
        uid = (user_id or "").strip() or "anonymous"
        task = await self.get_task(tid)
        if not task or task.user_id != uid:
            return None

        steps = list(task.steps_by_id.values())
        steps.sort(key=lambda s: str(s.get("startTime") or ""))
        return {
            "taskId": tid,
            "kind": task.kind,
            "status": task.status,
            "progress": float(task.progress or 0.0),
            "steps": steps,
            "error": task.error,
            "first_seq": task.seq_offset + 1,
            "last_seq": task.last_seq,
        }

    async def _append_event(self, task: QuestionLibraryTask, event: Dict[str, Any]) -> None:
        raw = dict(event or {})
        raw.pop("seq", None)

        event_type = str(raw.get("type") or raw.get("event") or "").strip() or "unknown"
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}

        # Back-compat: allow events that put fields at the top-level.
        for key in ("step", "progress", "result", "error"):
            if key in raw:
                data[key] = raw.get(key)

        payload = {
            "taskId": task.task_id,
            "type": event_type,
            "data": data,
        }

        # Track latest step snapshot.
        step = data.get("step") if isinstance(data, dict) else None
        if isinstance(step, dict):
            step_id = str(step.get("id") or "").strip()
            if step_id:
                task.steps_by_id[step_id] = step

        # Track progress (0..100).
        if event_type == "progress":
            try:
                task.progress = float((data or {}).get("progress") or 0.0)
            except Exception:
                logger.debug("question_library_progress_parse_failed", extra={"task_id": task.task_id}, exc_info=True)

        async with task.cond:
            task.last_seq += 1
            payload["seq"] = task.last_seq
            task.events.append(payload)
            task.updated_at_s = _now_s()

            if len(task.events) > self._max_events_per_task:
                drop_n = len(task.events) - self._max_events_per_task
                if drop_n > 0:
                    task.events = task.events[drop_n:]
                    task.seq_offset += drop_n

            task.cond.notify_all()

    async def append_event(self, task: QuestionLibraryTask, event: Dict[str, Any]) -> None:
        await self._append_event(task, event)

    async def fail_task(self, task: QuestionLibraryTask, message: str) -> None:
        task.status = "failed"
        task.error = message
        await self._append_event(task, {"type": "error", "data": {"error": message}})
        async with task.cond:
            task.cond.notify_all()

    async def complete_task(self, task: QuestionLibraryTask) -> None:
        task.status = "completed"
        task.progress = 100.0
        async with task.cond:
            task.cond.notify_all()

    async def shutdown(self, *, reason: str = "server_shutdown") -> None:
        """Best-effort graceful shutdown: cancel running tasks and persist terminal state."""

        msg = str(reason or "server_shutdown").strip() or "server_shutdown"

        async with self._lock:
            tasks = list(self._tasks.values())

        for task in tasks:
            if task.status != "running":
                continue

            task.status = "failed"
            task.error = msg

            try:
                await self._append_event(
                    task,
                    {"type": "warning", "data": {"message": "Task canceled due to server shutdown.", "reason": msg}},
                )
            except Exception:
                logger.debug("question_library_shutdown_append_event_failed", extra={"task_id": task.task_id}, exc_info=True)

            try:
                await db_append_task_event(
                    user_id=task.user_id,
                    task_id=task.task_id,
                    event_type="warning",
                    payload={"message": "Task canceled due to server shutdown.", "reason": msg},
                    seq=None,
                    progress=float(task.progress or 0.0),
                )
            except Exception:
                # Best-effort only: DB might be shutting down too.
                pass

            try:
                await db_update_task_status(
                    user_id=task.user_id,
                    task_id=task.task_id,
                    status="failed",
                    error={"message": msg},
                    ended_at=utcnow_naive(),
                )
            except Exception:
                pass

            if task.runner and not task.runner.done():
                task.runner.cancel()

            async with task.cond:
                task.cond.notify_all()

    def _gc_locked(self) -> None:
        now = _now_s()
        expired: List[str] = []
        for tid, task in self._tasks.items():
            age_s = now - float(task.updated_at_s or task.created_at_s or now)
            if age_s > self._task_ttl_s:
                expired.append(tid)

        for tid in expired:
            task = self._tasks.pop(tid, None)
            if task and task.runner and not task.runner.done():
                task.runner.cancel()

    def _drop_oldest_locked(self) -> None:
        if not self._tasks:
            return
        oldest = min(self._tasks.values(), key=lambda t: float(t.updated_at_s or t.created_at_s or 0.0))
        try:
            if oldest.runner and not oldest.runner.done():
                oldest.runner.cancel()
        except Exception:
            logger.debug("question_library_runner_cancel_failed", extra={"task_id": oldest.task_id}, exc_info=True)
        self._tasks.pop(oldest.task_id, None)
