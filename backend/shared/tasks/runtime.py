from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from backend.core import business_metrics
from backend.core.logging_utils import get_logger, get_request_id, get_trace_id
from backend.core.time_utils import utcnow_naive
from backend.shared.tasks import metrics as task_metrics
from backend.shared.tasks.store import TaskEventWrite, TaskStore

logger = get_logger(__name__)


def _now_s() -> float:
    return time.time()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clip(text: str, *, max_chars: int) -> str:
    s = str(text or "").strip()
    if max_chars <= 0:
        return ""
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


@dataclass
class RuntimeTask:
    task_id: str
    user_id: str
    task_type: str
    title: str
    request: Dict[str, Any] = field(default_factory=dict)
    parent_task_id: Optional[str] = None

    created_at_s: float = field(default_factory=_now_s)
    updated_at_s: float = field(default_factory=_now_s)
    status: str = "running"  # running|paused|pending_review|completed|failed|canceled
    error: Optional[str] = None
    progress: float = 0.0

    # seq starts at 1; `events[i-1]["seq"] == i` (after applying `seq_offset`).
    events: List[Dict[str, Any]] = field(default_factory=list)
    last_seq: int = 0
    seq_offset: int = 0  # number of dropped events; first stored seq is seq_offset + 1

    # Latest step snapshot (for status endpoints).
    steps_by_id: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Notified when events/status change.
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)

    # Runner task (created by runtime).
    runner: Optional[asyncio.Task] = None
    runner_factory: Optional[Callable[["RuntimeTask"], Awaitable[None]]] = None

    # Domain-specific extra state (resumable tasks can stash metadata here).
    meta: Dict[str, Any] = field(default_factory=dict)

    # Durable persistence is batched. Live SSE reads `events` directly from memory;
    # this queue is flushed for reconnect replay and terminal recovery.
    pending_persist_events: List[TaskEventWrite] = field(default_factory=list)
    event_flush_task: Optional[asyncio.Task] = None
    event_flush_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class TaskRuntime:
    """Unified in-memory task runtime with DB-backed persistence.

    The runtime keeps a bounded in-memory replay buffer for live SSE streaming
    and writes all events/status updates to the DB task store for durability.
    """

    def __init__(
        self,
        *,
        store: TaskStore,
        max_tasks: int = 200,
        task_ttl_s: int = 60 * 60,
        max_events_per_task: int = 8000,
        task_event_flush_interval_ms: int = 500,
        task_event_batch_size: int = 50,
    ) -> None:
        self._store = store
        self._tasks: Dict[str, RuntimeTask] = {}
        self._lock = asyncio.Lock()

        self._max_tasks = max(1, int(max_tasks or 200))
        self._task_ttl_s = max(60, int(task_ttl_s or (60 * 60)))
        self._max_events_per_task = max(200, int(max_events_per_task or 8000))
        self._event_flush_interval_s = max(0.0, float(task_event_flush_interval_ms or 0) / 1000.0)
        self._event_batch_size = max(1, int(task_event_batch_size or 50))

    async def restart_recovery(self, *, reason: str = "server_restarted") -> None:
        """Best-effort startup hook to fail orphaned DB tasks left as running."""

        try:
            await self._store.fail_running_tasks_on_startup(reason=reason)
        except Exception:
            logger.warning("task_runtime_restart_recovery_failed", extra={"reason": reason}, exc_info=True)

    async def shutdown(self, *, reason: str = "server_shutdown") -> None:
        """Best-effort graceful shutdown: cancel running tasks and persist terminal state."""

        async with self._lock:
            tasks = list(self._tasks.values())

        for task in tasks:
            if task.status != "running":
                try:
                    await self.flush_task_events(task)
                except Exception:
                    logger.warning(
                        "task_runtime_shutdown_flush_failed",
                        extra={"task_id": task.task_id, "user_id": task.user_id, "reason": reason},
                        exc_info=True,
                    )
                continue
            try:
                await self.cancel_task(task_id=task.task_id, user_id=task.user_id, reason=reason)
            except Exception:
                logger.warning(
                    "task_runtime_shutdown_cancel_failed",
                    extra={"task_id": task.task_id, "user_id": task.user_id, "reason": reason},
                    exc_info=True,
                )

    async def get_task(self, task_id: str) -> Optional[RuntimeTask]:
        tid = str(task_id or "").strip()
        if not tid:
            return None
        async with self._lock:
            self._gc_locked()
            return self._tasks.get(tid)

    async def create_task(
        self,
        *,
        task_id: str,
        user_id: str,
        task_type: str,
        title: str,
        request: Dict[str, Any],
        runner_factory: Callable[[RuntimeTask], Awaitable[None]],
        parent_task_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
        starter_event: Optional[Dict[str, Any]] = None,
    ) -> RuntimeTask:
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("missing_task_id")
        uid = str(user_id or "").strip() or "anonymous"
        ttype = str(task_type or "").strip() or "unknown"
        ttl = str(title or "").strip() or ttype
        req = request if isinstance(request, dict) else {}
        parent = str(parent_task_id or "").strip() or None

        task = RuntimeTask(
            task_id=tid,
            user_id=uid,
            task_type=ttype,
            title=_clip(ttl, max_chars=200),
            request=dict(req),
            parent_task_id=parent,
            runner_factory=runner_factory,
            meta=dict(meta or {}),
        )

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

            self._tasks[tid] = task

        # Persist DB row early so SSE pollers can attach even if the runner fails.
        try:
            await self._store.upsert_task(
                user_id=uid,
                task_id=tid,
                task_type=ttype,
                title=task.title,
                status="running",
                progress=0.0,
                request=dict(req),
                parent_task_id=parent,
                started_at=utcnow_naive(),
            )
        except Exception:
            logger.exception("task_runtime_upsert_failed", extra={"task_id": tid, "user_id": uid, "task_type": ttype})

        # A starter event helps the frontend render immediately.
        starter = starter_event
        if not isinstance(starter, dict) or not starter:
            starter = {
                "type": "step",
                "step": {
                    "id": "task_started",
                    "title": "任务开始",
                    "status": "running",
                    "startTime": _now_iso(),
                    "toolName": ttype,
                    "input": dict(req),
                },
            }
        await self.append_event(task, starter)

        if task.status != "running":
            return task
        task.runner = asyncio.create_task(self._run_task(task))
        return task

    async def _run_task(self, task: RuntimeTask) -> None:
        try:
            if not task.runner_factory:
                raise RuntimeError("missing_runner_factory")
            await task.runner_factory(task)
        except asyncio.CancelledError:
            # Lifecycle methods will persist terminal state; avoid double-writing.
            raise
        except Exception as exc:  # pragma: no cover
            logger.exception(
                "task_runtime_runner_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id, "task_type": task.task_type},
            )
            try:
                await self.fail_task(task, str(exc))
            except Exception:
                logger.warning(
                    "task_runtime_fail_task_after_runner_error_failed",
                    extra={"task_id": task.task_id, "user_id": task.user_id, "task_type": task.task_type},
                    exc_info=True,
                )

    def _gc_locked(self) -> None:
        now = _now_s()
        dead: List[str] = []
        for tid, task in self._tasks.items():
            age_s = now - float(task.updated_at_s or task.created_at_s or now)
            if age_s < float(self._task_ttl_s or 3600):
                continue
            # Only evict non-running tasks; for running tasks we keep them in memory so
            # lifecycle ops (cancel/pause) can still cooperate.
            if task.status == "running":
                continue
            dead.append(tid)

        for tid in dead:
            self._tasks.pop(tid, None)

    def _drop_oldest_locked(self) -> None:
        # Prefer dropping terminal tasks; if none, drop oldest non-running; if still
        # none, drop oldest running as a last resort.
        items = list(self._tasks.items())
        if not items:
            return

        def key(it) -> tuple[int, float]:
            _tid, task = it
            status = str(task.status or "")
            terminal = 0 if status in {"completed", "failed", "canceled", "cancelled"} else 1
            running = 1 if status == "running" else 0
            # Lower is better to drop first: terminal first, then non-running, then running.
            return (terminal + running, float(task.updated_at_s or task.created_at_s or 0.0))

        items.sort(key=key)
        drop_id = items[0][0]
        t = self._tasks.get(drop_id)
        if t and t.runner and not t.runner.done():
            t.runner.cancel()
        self._tasks.pop(drop_id, None)

    def _normalize_event_payload(self, *, task_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        raw = dict(event or {})
        raw.pop("seq", None)
        raw.pop("task_id", None)
        raw.pop("taskId", None)

        created_at = ""
        if isinstance(raw.get("created_at"), str):
            created_at = str(raw.get("created_at") or "").strip()
        elif isinstance(raw.get("createdAt"), str):
            created_at = str(raw.get("createdAt") or "").strip()
        if not created_at:
            created_at = _now_iso()

        event_type = str(raw.get("type") or raw.get("event") or "").strip() or "unknown"
        data = dict(raw.get("data") or {}) if isinstance(raw.get("data"), dict) else {}
        trace_id = str(raw.get("trace_id") or raw.get("traceId") or data.get("trace_id") or data.get("traceId") or "").strip()
        if not trace_id:
            trace_id = get_trace_id() or get_request_id()

        # Back-compat and generality:
        # Many domains emit events as {type, ...payloadFields} instead of {type, data:{...}}.
        # Preserve *all* top-level payload fields (excluding reserved keys) into `data`.
        reserved = {"type", "event", "data", "created_at", "createdAt", "trace_id", "traceId"}
        for key, value in raw.items():
            if key in reserved:
                continue
            data[key] = value

        payload = {"taskId": task_id, "type": event_type, "data": data, "created_at": created_at}
        if trace_id:
            payload["trace_id"] = trace_id
        return payload

    async def append_event(self, task: RuntimeTask, event: Dict[str, Any]) -> None:
        payload = self._normalize_event_payload(task_id=task.task_id, event=event)
        event_type = str(payload.get("type") or "").strip() or "event"
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}

        progress_value: Optional[float] = None
        if event_type == "progress":
            try:
                progress_value = float((data or {}).get("progress") or 0.0)
                task.progress = progress_value
            except (TypeError, ValueError):
                progress_value = None

        step = (data or {}).get("step") if isinstance(data, dict) else None
        if isinstance(step, dict):
            step_id = str(step.get("id") or "").strip()
            if step_id:
                task.steps_by_id[step_id] = step

        seq = 0
        async with task.cond:
            task.last_seq += 1
            seq = int(task.last_seq or 0)
            payload["seq"] = seq
            task.events.append(payload)
            task.updated_at_s = _now_s()

            if len(task.events) > self._max_events_per_task:
                drop_n = len(task.events) - self._max_events_per_task
                if drop_n > 0:
                    task.events = task.events[drop_n:]
                    task.seq_offset += drop_n

            task.cond.notify_all()

        await self._enqueue_event_write(
            task,
            TaskEventWrite(
                event_type=event_type,
                payload=data if isinstance(data, dict) else {},
                seq=seq if seq > 0 else None,
                progress=progress_value,
            ),
        )

    async def _enqueue_event_write(self, task: RuntimeTask, write: TaskEventWrite) -> None:
        flush_now = False
        pending = 0
        async with task.cond:
            task.pending_persist_events.append(write)
            pending = len(task.pending_persist_events)
            flush_now = pending >= self._event_batch_size
            if not flush_now and (task.event_flush_task is None or task.event_flush_task.done()):
                task.event_flush_task = asyncio.create_task(self._delayed_flush_task_events(task))

        task_metrics.event_queued(task_type=task.task_type, event_type=write.event_type, pending=pending)

        if flush_now:
            await self.flush_task_events(task)

    async def _delayed_flush_task_events(self, task: RuntimeTask) -> None:
        try:
            if self._event_flush_interval_s > 0:
                await asyncio.sleep(self._event_flush_interval_s)
            await self.flush_task_events(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "task_runtime_delayed_event_flush_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id, "task_type": task.task_type},
                exc_info=True,
            )

    async def flush_task_events(self, task: RuntimeTask) -> None:
        current = asyncio.current_task()
        async with task.cond:
            scheduled = task.event_flush_task
            if scheduled is not None and scheduled is not current and not scheduled.done():
                scheduled.cancel()
            if scheduled is current or scheduled is not None:
                task.event_flush_task = None

        async with task.event_flush_lock:
            while True:
                async with task.cond:
                    batch = list(task.pending_persist_events[: self._event_batch_size])
                    if not batch:
                        task_metrics.pending_events(task_type=task.task_type, pending=0)
                        return
                    del task.pending_persist_events[: len(batch)]
                    pending = len(task.pending_persist_events)

                started_s = task_metrics.now_s()
                try:
                    await self._store.append_task_events(user_id=task.user_id, task_id=task.task_id, events=batch)
                except Exception:
                    async with task.cond:
                        task.pending_persist_events = batch + task.pending_persist_events
                        pending = len(task.pending_persist_events)
                    task_metrics.pending_events(task_type=task.task_type, pending=pending)
                    logger.exception(
                        "task_runtime_event_batch_write_failed",
                        extra={
                            "task_id": task.task_id,
                            "user_id": task.user_id,
                            "task_type": task.task_type,
                            "event_count": len(batch),
                        },
                    )
                    return

                duration_s = task_metrics.now_s() - started_s
                task_metrics.event_flush(
                    task_type=task.task_type,
                    status="ok",
                    count=len(batch),
                    duration_s=duration_s,
                )
                task_metrics.pending_events(task_type=task.task_type, pending=pending)

    async def complete_task(self, task: RuntimeTask, *, result: Optional[Dict[str, Any]] = None) -> None:
        task.status = "completed"
        task.progress = 100.0
        task.updated_at_s = _now_s()
        business_metrics.record_task_terminal(task_type=task.task_type, status="completed")
        await self.flush_task_events(task)
        try:
            await self._store.update_task_status(
                user_id=task.user_id,
                task_id=task.task_id,
                status="completed",
                progress=100.0,
                result=result or {},
                ended_at=utcnow_naive(),
            )
        except Exception:
            logger.exception(
                "task_runtime_complete_write_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id, "task_type": task.task_type},
            )
        async with task.cond:
            task.cond.notify_all()

    async def defer_task(
        self,
        task: RuntimeTask,
        *,
        status: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        next_status = str(status or "").strip() or "pending_review"
        task.status = next_status
        task.updated_at_s = _now_s()
        await self.flush_task_events(task)
        try:
            await self._store.update_task_status(
                user_id=task.user_id,
                task_id=task.task_id,
                status=next_status,
                progress=float(task.progress or 0.0),
                result=result or {},
                error={},
            )
        except Exception:
            logger.exception(
                "task_runtime_defer_write_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id, "task_type": task.task_type},
            )
        async with task.cond:
            task.cond.notify_all()

    async def fail_task(
        self,
        task: RuntimeTask,
        message: str,
        *,
        error: Optional[Dict[str, Any]] = None,
        emit_event: bool = True,
    ) -> None:
        task.status = "failed"
        task.error = message
        task.updated_at_s = _now_s()
        business_metrics.record_task_terminal(task_type=task.task_type, status="failed")

        if emit_event:
            # Emit an error event (best-effort) so live clients get a terminal signal.
            try:
                await self.append_event(task, {"type": "error", "data": {"error": message}})
            except Exception:
                logger.warning(
                    "task_runtime_error_event_emit_failed",
                    extra={"task_id": task.task_id, "user_id": task.user_id, "task_type": task.task_type},
                    exc_info=True,
                )

        await self.flush_task_events(task)
        try:
            await self._store.update_task_status(
                user_id=task.user_id,
                task_id=task.task_id,
                status="failed",
                error=error or {"message": message},
                ended_at=utcnow_naive(),
            )
        except Exception:
            logger.exception(
                "task_runtime_fail_write_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id, "task_type": task.task_type},
            )
        async with task.cond:
            task.cond.notify_all()

    async def pause_task(self, *, task_id: str, user_id: str) -> bool:
        task = await self.get_task(task_id)
        uid = str(user_id or "").strip()
        if not task or task.user_id != uid:
            return False
        if task.status != "running":
            return True

        task.status = "paused"
        task.updated_at_s = _now_s()
        if task.runner and not task.runner.done():
            task.runner.cancel()

        await self.append_event(
            task,
            {
                "type": "step",
                "step": {
                    "id": "task_paused",
                    "title": "任务已暂停",
                    "status": "paused",
                    "startTime": _now_iso(),
                    "toolName": task.task_type,
                },
            },
        )

        await self.flush_task_events(task)
        try:
            await self._store.update_task_status(user_id=uid, task_id=task.task_id, status="paused", error={})
        except Exception:
            logger.exception(
                "task_runtime_pause_write_failed",
                extra={"task_id": task.task_id, "user_id": uid, "task_type": task.task_type},
            )

        async with task.cond:
            task.cond.notify_all()
        return True

    async def resume_task(self, *, task_id: str, user_id: str) -> bool:
        task = await self.get_task(task_id)
        uid = str(user_id or "").strip()
        if not task or task.user_id != uid:
            return False
        if task.status == "running":
            return True
        if task.status != "paused":
            return False
        if not task.runner_factory:
            return False

        task.status = "running"
        task.error = None
        task.updated_at_s = _now_s()

        await self.append_event(
            task,
            {
                "type": "step",
                "step": {
                    "id": "task_resumed",
                    "title": "任务继续执行",
                    "status": "running",
                    "startTime": _now_iso(),
                    "toolName": task.task_type,
                },
            },
        )

        await self.flush_task_events(task)
        try:
            await self._store.update_task_status(user_id=uid, task_id=task.task_id, status="running", error={})
        except Exception:
            logger.exception(
                "task_runtime_resume_write_failed",
                extra={"task_id": task.task_id, "user_id": uid, "task_type": task.task_type},
            )

        task.runner = asyncio.create_task(self._run_task(task))
        async with task.cond:
            task.cond.notify_all()
        return True

    async def cancel_task(self, *, task_id: str, user_id: str, reason: str = "Task cancelled") -> bool:
        task = await self.get_task(task_id)
        uid = str(user_id or "").strip()
        if not task or task.user_id != uid:
            return False
        if task.status in {"completed", "failed", "canceled", "cancelled"}:
            return True

        task.status = "canceled"
        task.error = reason
        task.updated_at_s = _now_s()
        business_metrics.record_task_terminal(task_type=task.task_type, status="canceled")
        if task.runner and not task.runner.done():
            task.runner.cancel()

        await self.append_event(
            task,
            {
                "type": "step",
                "step": {
                    "id": "task_canceled",
                    "title": "任务已取消",
                    "status": "failed",
                    "startTime": _now_iso(),
                    "toolName": task.task_type,
                    "error": reason,
                },
            },
        )

        await self.flush_task_events(task)
        try:
            await self._store.update_task_status(
                user_id=uid,
                task_id=task.task_id,
                status="canceled",
                error={"message": reason},
                ended_at=utcnow_naive(),
            )
        except Exception:
            logger.exception(
                "task_runtime_cancel_write_failed",
                extra={"task_id": task.task_id, "user_id": uid, "task_type": task.task_type},
            )

        async with task.cond:
            task.cond.notify_all()
        return True

    async def stream(self, task_id: str, *, after_seq: int = 0, heartbeat_s: float = 4.0) -> AsyncIterator[dict]:
        """Stream in-memory events for a running task (SSE replay), with heartbeats.

        If the client asks for a sequence that is too old (events dropped), emit an
        error event that instructs the client to restart.
        """

        tid = str(task_id or "").strip()
        if not tid:
            yield {"type": "error", "error": "missing_task_id", "created_at": _now_iso()}
            return

        last_sent_seq = max(0, int(after_seq or 0))
        last_ping_at = 0.0
        stream_metrics = None

        try:
            while True:
                task = await self.get_task(tid)
                if not task:
                    yield {
                        "taskId": tid,
                        "seq": last_sent_seq,
                        "type": "error",
                        "data": {"error": "task_not_found"},
                        "created_at": _now_iso(),
                    }
                    return
                if stream_metrics is None:
                    stream_metrics = task_metrics.sse_connection(task.task_type)
                    stream_metrics.__enter__()

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
                        "created_at": _now_iso(),
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

                now = _now_s()
                if now - last_ping_at >= max(1.0, float(heartbeat_s or 4.0)):
                    last_ping_at = now
                    yield {
                        "taskId": tid,
                        "seq": last_sent_seq,
                        "type": "ping",
                        "data": {"status": task.status, "last_seq": last_sent_seq},
                        "created_at": _now_iso(),
                    }

                async with task.cond:
                    try:
                        await asyncio.wait_for(
                            task.cond.wait_for(lambda: task.last_seq > last_sent_seq or task.status != "running"),
                            timeout=max(0.5, float(heartbeat_s or 4.0)),
                        )
                    except asyncio.TimeoutError:
                        continue
        finally:
            if stream_metrics is not None:
                stream_metrics.__exit__(None, None, None)

    async def status_payload(
        self,
        *,
        task_id: str,
        user_id: str,
        include_events: bool = False,
        events_limit: int = 500,
    ) -> Optional[dict]:
        tid = str(task_id or "").strip()
        uid = str(user_id or "").strip() or "anonymous"
        task = await self.get_task(tid)
        if not task or task.user_id != uid:
            return None

        steps = list(task.steps_by_id.values())
        steps.sort(key=lambda s: str(s.get("startTime") or ""))
        payload = {
            "taskId": tid,
            "type": task.task_type,
            "status": task.status,
            "progress": float(task.progress or 0.0),
            "steps": steps,
            "error": task.error,
            "first_seq": task.seq_offset + 1,
            "last_seq": task.last_seq,
        }
        if include_events:
            limit = max(1, min(int(events_limit or 500), 5000))
            payload["events"] = list(task.events[-limit:])
        return payload
