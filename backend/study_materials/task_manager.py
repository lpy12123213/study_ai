from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.agent.core import AgentCore


def _now_s() -> float:
    return time.time()


@dataclass
class StudyMaterialsTask:
    task_id: str
    query: str
    user_id: str
    subject: str = ""
    options: Dict[str, Any] = field(default_factory=dict)
    created_at_s: float = field(default_factory=_now_s)
    updated_at_s: float = field(default_factory=_now_s)
    status: str = "running"  # running|completed|failed
    error: Optional[str] = None

    # seq starts at 1; `events[i-1]["seq"] == i`.
    events: List[Dict[str, Any]] = field(default_factory=list)
    last_seq: int = 0
    seq_offset: int = 0  # number of dropped events; first stored seq is seq_offset + 1

    # Notified when events/status change.
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)

    # Runner task (created by manager).
    runner: Optional[asyncio.Task] = None


class StudyMaterialsTaskManager:
    """In-memory study-materials task manager with SSE replay support.

    Goals:
    - Allow browser refresh/reconnect without losing progress.
    - Keep the generation running even if the client disconnects.
    - Provide heartbeats for long-running tool calls (handled by stream()).
    """

    def __init__(
        self,
        *,
        max_tasks: int = 50,
        task_ttl_s: int = 60 * 60,
        max_events_per_task: int = 5000,
    ) -> None:
        self._tasks: Dict[str, StudyMaterialsTask] = {}
        self._lock = asyncio.Lock()
        self._max_tasks = max(1, int(max_tasks))
        self._task_ttl_s = max(60, int(task_ttl_s))
        self._max_events_per_task = max(100, int(max_events_per_task))

    async def create_task(
        self,
        *,
        query: str,
        user_id: str,
        subject: str = "",
        options: Optional[Dict[str, Any]] = None,
    ) -> StudyMaterialsTask:
        query = (query or "").strip()
        user_id = (user_id or "").strip() or "anonymous"
        subject = (subject or "").strip()
        options = options if isinstance(options, dict) else {}

        task_id = uuid.uuid4().hex
        task = StudyMaterialsTask(task_id=task_id, query=query, user_id=user_id, subject=subject, options=dict(options))

        async with self._lock:
            self._gc_locked()
            if len(self._tasks) >= self._max_tasks:
                self._drop_oldest_locked()
            self._tasks[task_id] = task

        await self._append_event(
            task,
            {
                "event": "task_started",
                "data": {
                    "task_id": task_id,
                    "status": "running",
                    "query": query,
                    "subject": subject,
                    "options": options,
                },
            },
        )

        task.runner = asyncio.create_task(self._run_task(task))
        return task

    async def get_task(self, task_id: str) -> Optional[StudyMaterialsTask]:
        tid = (task_id or "").strip()
        if not tid:
            return None
        async with self._lock:
            self._gc_locked()
            return self._tasks.get(tid)

    async def stream(
        self,
        task_id: str,
        *,
        after_seq: int = 0,
        heartbeat_s: float = 4.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        tid = (task_id or "").strip()
        if not tid:
            yield {"event": "error", "data": {"message": "Missing task_id"}}
            return

        task = await self.get_task(tid)
        if not task:
            yield {"event": "error", "data": {"message": f"Task not found: {tid}"}}
            return

        last_sent_seq = max(0, int(after_seq or 0))
        while True:
            # Flush backlog first.
            if task.last_seq > last_sent_seq:
                first_seq = task.seq_offset + 1
                if last_sent_seq < first_seq - 1:
                    # The client is too far behind (events were dropped); emit a soft error so
                    # the UI can restart the generation if needed.
                    yield {
                        "event": "warning",
                        "data": {
                            "task_id": tid,
                            "message": "Event backlog truncated; please restart if output looks incomplete.",
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
                continue

            if task.status != "running":
                # Completed/failed and no more events to replay.
                return

            # Wait for new events, but keep the connection alive with pings.
            async with task.cond:
                try:
                    await asyncio.wait_for(
                        task.cond.wait_for(lambda: task.last_seq > last_sent_seq or task.status != "running"),
                        timeout=max(0.5, float(heartbeat_s or 4.0)),
                    )
                except asyncio.TimeoutError:
                    yield {
                        "event": "ping",
                        "data": {
                            "task_id": tid,
                            "status": task.status,
                            "last_seq": task.last_seq,
                            "updated_at_s": task.updated_at_s,
                        },
                    }

    async def _append_event(self, task: StudyMaterialsTask, event: Dict[str, Any]) -> None:
        payload = dict(event or {})
        payload.pop("seq", None)
        payload["task_id"] = task.task_id

        async with task.cond:
            task.last_seq += 1
            payload["seq"] = task.last_seq
            task.events.append(payload)
            task.updated_at_s = _now_s()

            # Prevent unbounded memory if something goes wrong.
            if len(task.events) > self._max_events_per_task:
                drop_n = len(task.events) - self._max_events_per_task
                if drop_n > 0:
                    task.events = task.events[drop_n:]
                    task.seq_offset += drop_n

            task.cond.notify_all()

    async def _fail_task(self, task: StudyMaterialsTask, message: str) -> None:
        task.status = "failed"
        task.error = message
        await self._append_event(task, {"event": "error", "data": {"message": message}})
        async with task.cond:
            task.cond.notify_all()

    async def _complete_task(self, task: StudyMaterialsTask) -> None:
        task.status = "completed"
        async with task.cond:
            task.cond.notify_all()

    async def _run_task(self, task: StudyMaterialsTask) -> None:
        agent = AgentCore()
        try:
            preferences = {}
            if (task.subject or "").strip():
                preferences["subject"] = str(task.subject or "").strip()

            async for evt in agent.run(task.query, user_id=task.user_id, preferences=preferences, options=task.options):
                # If the task already failed (e.g. due to server shutdown), stop.
                if task.status != "running":
                    break
                await self._append_event(task, evt)

                kind = str(evt.get("event") or "")
                if kind == "done":
                    await self._complete_task(task)
                elif kind == "error":
                    msg = ""
                    data = evt.get("data")
                    if isinstance(data, dict):
                        msg = str(data.get("message") or "")
                    task.status = "failed"
                    task.error = msg or "Generation failed"
                    async with task.cond:
                        task.cond.notify_all()
        except asyncio.CancelledError:
            await self._fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            await self._fail_task(task, str(exc))
        finally:
            if task.status == "running":
                # If we exited without a terminal event, mark as failed so clients stop waiting forever.
                await self._fail_task(task, "Task ended unexpectedly")

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
        tid = oldest.task_id
        task = self._tasks.pop(tid, None)
        if task and task.runner and not task.runner.done():
            task.runner.cancel()
