from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional


def _now_s() -> float:
    return time.time()


@dataclass
class PaperComposeTask:
    task_id: str
    user_id: str
    request: Dict[str, Any]
    created_at_s: float = field(default_factory=_now_s)
    updated_at_s: float = field(default_factory=_now_s)
    status: str = "running"  # running|paused|completed|failed
    error: Optional[str] = None
    progress: float = 0.0

    # seq starts at 1; `events[i-1]["seq"] == i`.
    events: List[Dict[str, Any]] = field(default_factory=list)
    last_seq: int = 0
    seq_offset: int = 0  # number of dropped events; first stored seq is seq_offset + 1

    # Latest step snapshot (for status endpoint).
    steps_by_id: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    runner: Optional[asyncio.Task] = None


class PaperComposeTaskManager:
    """In-memory task manager for blueprint compose tasks with SSE replay support."""

    def __init__(
        self,
        *,
        max_tasks: int = 50,
        task_ttl_s: int = 60 * 60,
        max_events_per_task: int = 4000,
    ) -> None:
        self._tasks: Dict[str, PaperComposeTask] = {}
        self._lock = asyncio.Lock()
        self._max_tasks = max(1, int(max_tasks))
        self._task_ttl_s = max(60, int(task_ttl_s))
        self._max_events_per_task = max(200, int(max_events_per_task))

    async def create_task(
        self,
        *,
        task_id: str,
        user_id: str,
        request: Dict[str, Any],
        runner_factory,
    ) -> PaperComposeTask:
        tid = (task_id or "").strip()
        if not tid:
            raise ValueError("missing_task_id")
        uid = (user_id or "").strip() or "anonymous"
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

            task = PaperComposeTask(task_id=tid, user_id=uid, request=dict(req))
            self._tasks[tid] = task

        await self._append_event(
            task,
            {
                "type": "step",
                "step": {
                    "id": "task_started",
                    "title": "开始组卷任务",
                    "status": "running",
                    "startTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "toolName": "compose_paper",
                    "input": {"taskId": tid},
                },
            },
        )

        task.runner = asyncio.create_task(runner_factory(task))
        return task

    async def get_task(self, task_id: str) -> Optional[PaperComposeTask]:
        tid = (task_id or "").strip()
        if not tid:
            return None
        async with self._lock:
            self._gc_locked()
            return self._tasks.get(tid)

    async def pause_task(self, *, task_id: str, user_id: str) -> bool:
        tid = (task_id or "").strip()
        uid = (user_id or "").strip() or "anonymous"
        if not tid:
            return False

        async with self._lock:
            task = self._tasks.get(tid)
            if not task or task.user_id != uid:
                return False
            if task.status != "running":
                return True
            task.status = "paused"

            if task.runner and not task.runner.done():
                task.runner.cancel()

        await self._append_event(
            task,
            {
                "type": "step",
                "step": {
                    "id": "task_paused",
                    "title": "任务已暂停",
                    "status": "paused",
                    "startTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "toolName": "compose_paper",
                },
            },
        )
        async with task.cond:
            task.cond.notify_all()
        return True

    async def resume_task(self, *, task_id: str, user_id: str, runner_factory) -> bool:
        tid = (task_id or "").strip()
        uid = (user_id or "").strip() or "anonymous"
        if not tid:
            return False

        task = await self.get_task(tid)
        if not task or task.user_id != uid:
            return False

        if task.status == "running":
            return True

        task.status = "running"
        task.error = None
        await self._append_event(
            task,
            {
                "type": "step",
                "step": {
                    "id": "task_resumed",
                    "title": "任务继续执行",
                    "status": "running",
                    "startTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "toolName": "compose_paper",
                },
            },
        )

        task.runner = asyncio.create_task(runner_factory(task))
        return True

    async def stream(
        self,
        task_id: str,
        *,
        after_seq: int = 0,
        heartbeat_s: float = 4.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        tid = (task_id or "").strip()
        if not tid:
            yield {"type": "error", "error": "Missing task_id"}
            return

        task = await self.get_task(tid)
        if not task:
            yield {"type": "error", "error": f"Task not found: {tid}"}
            return

        last_sent_seq = max(0, int(after_seq or 0))
        while True:
            if task.last_seq > last_sent_seq:
                first_seq = task.seq_offset + 1
                if last_sent_seq < first_seq - 1:
                    yield {
                        "type": "error",
                        "error": "Event backlog truncated; please restart.",
                        "first_seq": first_seq,
                        "last_seq": task.last_seq,
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
                return

            async with task.cond:
                try:
                    await asyncio.wait_for(
                        task.cond.wait_for(lambda: task.last_seq > last_sent_seq or task.status != "running"),
                        timeout=max(0.5, float(heartbeat_s or 4.0)),
                    )
                except asyncio.TimeoutError:
                    yield {
                        "type": "progress",
                        "progress": float(task.progress or 0.0),
                        "taskId": tid,
                        "status": task.status,
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
            "status": task.status,
            "progress": float(task.progress or 0.0),
            "steps": steps,
            "error": task.error,
        }

    async def _append_event(self, task: PaperComposeTask, event: Dict[str, Any]) -> None:
        raw = dict(event or {})
        raw.pop("seq", None)

        event_type = str(raw.get("type") or raw.get("event") or "").strip() or "unknown"
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}

        # Back-compat: legacy compose events put fields at the top-level (step/progress/result/error).
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
                pass

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

    async def append_event(self, task: PaperComposeTask, event: Dict[str, Any]) -> None:
        await self._append_event(task, event)

    async def fail_task(self, task: PaperComposeTask, message: str) -> None:
        task.status = "failed"
        task.error = message
        await self._append_event(task, {"type": "error", "data": {"error": message}})
        async with task.cond:
            task.cond.notify_all()

    async def complete_task(self, task: PaperComposeTask) -> None:
        task.status = "completed"
        task.progress = 100.0
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
            pass
        self._tasks.pop(oldest.task_id, None)
