from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging_utils import get_logger
from backend.core.time_utils import utcnow_naive
from backend.database.engine import async_session_maker
from backend.database.schema import Task, TaskDurationAggregate, TaskEvent

logger = get_logger(__name__)

TASK_DURATION_EMA_ALPHA = 0.2


def _get_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


TASK_JSON_MAX_CHARS = max(10_000, min(_get_int("TASK_JSON_MAX_CHARS", 200_000), 5_000_000))


def _isoformat_utc_z(dt: Optional[datetime]) -> str:
    """Serialize naive DB datetimes (stored as UTC) into an ISO-8601 UTC string.

    Frontend `Date.parse()` treats ISO strings without timezone as local time, which
    introduces an 8-hour offset in Asia/Shanghai. Always include timezone.
    """

    if not dt:
        return ""
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except (AttributeError, OSError, ValueError):
        try:
            raw = dt.isoformat()
        except AttributeError:
            return ""
        return f"{raw}Z" if raw and not raw.endswith("Z") else raw


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64]


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _json_dumps(value: Any, *, default: str) -> str:
    if value is None:
        return default
    raw: str
    if isinstance(value, str):
        raw = value
    else:
        try:
            raw = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return default

    if len(raw) <= TASK_JSON_MAX_CHARS:
        return raw

    # Avoid DB row bloat from huge payloads (e.g. full LLM transcripts). We keep
    # a short preview so operators can still debug from the DB.
    preview_max = min(20_000, max(1_000, int(TASK_JSON_MAX_CHARS // 10)))
    truncated_obj = {"_truncated": True, "original_chars": len(raw), "preview": raw[:preview_max]}
    try:
        truncated = json.dumps(truncated_obj, ensure_ascii=False)
        if len(truncated) <= TASK_JSON_MAX_CHARS:
            return truncated
    except Exception:
        logger.warning("task_json_truncate_failed", exc_info=True)
    return default


def _json_loads(value: str, *, default: Any) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _task_to_dict(task: Task, *, include_payloads: bool = True) -> dict:
    out = {
        "id": task.id,
        "user_id": task.user_id,
        "task_type": task.task_type,
        "title": task.title,
        "status": task.status,
        "progress": float(task.progress or 0.0),
        "last_seq": int(task.last_seq or 0),
        "parent_task_id": task.parent_task_id,
        "created_at": _isoformat_utc_z(task.created_at),
        "updated_at": _isoformat_utc_z(task.updated_at),
        "started_at": _isoformat_utc_z(task.started_at),
        "ended_at": _isoformat_utc_z(task.ended_at),
    }
    if include_payloads:
        out["request"] = _json_loads(task.request_json, default={})
        out["result"] = _json_loads(task.result_json, default={})
        out["error"] = _json_loads(task.error_json, default={})
    return out


def _event_to_dict(evt: TaskEvent) -> dict:
    return {
        "taskId": evt.task_id,
        "seq": int(evt.seq or 0),
        "type": evt.event_type,
        "data": _json_loads(evt.payload_json, default={}),
        "created_at": _isoformat_utc_z(evt.created_at),
    }


def _task_duration_seconds(task: Task) -> Optional[float]:
    if str(task.status or "").strip() != "completed":
        return None
    started_at = task.started_at
    ended_at = task.ended_at
    if not started_at or not ended_at:
        return None
    try:
        duration = (ended_at - started_at).total_seconds()
    except (OverflowError, TypeError, ValueError):
        return None
    if duration < 0:
        return None
    return float(duration)


async def upsert_task_duration_aggregate(
    *,
    task_type: str,
    duration_seconds: float,
    session: Optional[AsyncSession] = None,
) -> Optional[TaskDurationAggregate]:
    ttype = str(task_type or "").strip()
    if not ttype:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            row = await upsert_task_duration_aggregate(
                task_type=ttype,
                duration_seconds=duration_seconds,
                session=session,
            )
            await session.commit()
            return row

    duration = float(duration_seconds or 0.0)
    res = await session.execute(select(TaskDurationAggregate).where(TaskDurationAggregate.task_type == ttype))
    row = res.scalar_one_or_none()
    now = utcnow_naive()

    if row is None:
        row = TaskDurationAggregate(
            task_type=ttype,
            completed_count=1,
            duration_sum_seconds=duration,
            duration_ema_seconds=duration,
            last_duration_seconds=duration,
            updated_at=now,
        )
        session.add(row)
    else:
        previous_count = int(row.completed_count or 0)
        previous_ema = float(row.duration_ema_seconds or 0.0)
        row.completed_count = previous_count + 1
        row.duration_sum_seconds = float(row.duration_sum_seconds or 0.0) + duration
        row.duration_ema_seconds = duration if previous_count <= 0 else (
            previous_ema * (1.0 - TASK_DURATION_EMA_ALPHA) + duration * TASK_DURATION_EMA_ALPHA
        )
        row.last_duration_seconds = duration
        row.updated_at = now

    await session.flush()
    return row


async def rebuild_task_duration_aggregates(*, session: Optional[AsyncSession] = None) -> int:
    own = session is None
    if own:
        async with async_session_maker() as session:
            rebuilt = await rebuild_task_duration_aggregates(session=session)
            await session.commit()
            return rebuilt

    await session.execute(delete(TaskDurationAggregate))
    await session.flush()

    stmt = (
        select(Task)
        .where(
            Task.status == "completed",
            Task.started_at.is_not(None),
            Task.ended_at.is_not(None),
        )
        .order_by(Task.ended_at.asc(), Task.started_at.asc(), Task.id.asc())
    )
    res = await session.execute(stmt)
    completed_tasks = res.scalars().all()

    rebuilt_types: set[str] = set()
    for task in completed_tasks:
        duration_seconds = _task_duration_seconds(task)
        if duration_seconds is None:
            continue
        task_type = str(task.task_type or "").strip()
        if not task_type:
            continue
        await upsert_task_duration_aggregate(
            task_type=task_type,
            duration_seconds=duration_seconds,
            session=session,
        )
        rebuilt_types.add(task_type)

    await session.flush()
    return len(rebuilt_types)


async def upsert_task(
    *,
    user_id: str,
    task_id: str,
    task_type: str,
    title: str,
    status: str = "running",
    progress: float = 0.0,
    parent_task_id: Optional[str] = None,
    request: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
    started_at: Optional[datetime] = None,
    ended_at: Optional[datetime] = None,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    tid = str(task_id or "").strip()
    if not tid:
        raise ValueError("missing_task_id")

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await upsert_task(
                user_id=uid,
                task_id=tid,
                task_type=task_type,
                title=title,
                status=status,
                progress=progress,
                parent_task_id=parent_task_id,
                request=request,
                result=result,
                error=error,
                started_at=started_at,
                ended_at=ended_at,
                session=session,
            )
            await session.commit()
            return out

    res = await session.execute(select(Task).where(Task.id == tid))
    existing = res.scalar_one_or_none()
    if existing and existing.user_id != uid:
        raise ValueError("task_id_conflict")

    if existing:
        existing.task_type = str(task_type or "").strip()
        existing.title = str(title or "").strip()
        existing.status = str(status or "").strip() or existing.status
        existing.progress = float(progress or 0.0)
        existing.parent_task_id = str(parent_task_id or "").strip() or None
        if request is not None:
            existing.request_json = _json_dumps(request, default="{}")
        if result is not None:
            existing.result_json = _json_dumps(result, default="{}")
        if error is not None:
            existing.error_json = _json_dumps(error, default="{}")
        if started_at is not None:
            existing.started_at = started_at
        if ended_at is not None:
            existing.ended_at = ended_at
        session.add(existing)
        await session.flush()
        await session.refresh(existing)
        return _task_to_dict(existing)

    task = Task(
        id=tid,
        user_id=uid,
        task_type=str(task_type or "").strip(),
        title=str(title or "").strip(),
        status=str(status or "").strip() or "running",
        progress=float(progress or 0.0),
        parent_task_id=str(parent_task_id or "").strip() or None,
        request_json=_json_dumps(request, default="{}"),
        result_json=_json_dumps(result, default="{}"),
        error_json=_json_dumps(error, default="{}"),
        started_at=started_at,
        ended_at=ended_at,
    )
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return _task_to_dict(task)


async def update_task_status(
    *,
    user_id: str,
    task_id: str,
    status: str,
    progress: Optional[float] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
    started_at: Optional[datetime] = None,
    ended_at: Optional[datetime] = None,
    session: Optional[AsyncSession] = None,
) -> bool:
    uid = _require_user_id(user_id)
    tid = str(task_id or "").strip()
    if not tid:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await update_task_status(
                user_id=uid,
                task_id=tid,
                status=status,
                progress=progress,
                result=result,
                error=error,
                started_at=started_at,
                ended_at=ended_at,
                session=session,
            )
            await session.commit()
            return ok

    res = await session.execute(select(Task).where(Task.id == tid, Task.user_id == uid))
    task = res.scalar_one_or_none()
    if not task:
        return False

    previous_status = str(task.status or "").strip()
    task.status = str(status or "").strip() or task.status
    if progress is not None:
        task.progress = float(progress or 0.0)
    if result is not None:
        task.result_json = _json_dumps(result, default="{}")
    if error is not None:
        task.error_json = _json_dumps(error, default="{}")
    if started_at is not None:
        task.started_at = started_at
    if ended_at is not None:
        task.ended_at = ended_at
    session.add(task)

    duration_seconds = _task_duration_seconds(task)
    if str(task.status or "").strip() == "completed" and previous_status != "completed":
        if duration_seconds is not None:
            await upsert_task_duration_aggregate(
                task_type=task.task_type,
                duration_seconds=duration_seconds,
                session=session,
            )

    await session.flush()
    return True


async def append_task_events(
    *,
    user_id: str,
    task_id: str,
    events: List[Any],
    session: Optional[AsyncSession] = None,
) -> int:
    uid = _require_user_id(user_id)
    tid = str(task_id or "").strip()
    if not tid:
        raise ValueError("missing_task_id")

    writes = [evt for evt in (events or []) if evt is not None]
    if not writes:
        return 0

    own = session is None
    if own:
        async with async_session_maker() as session:
            next_seq = await append_task_events(
                user_id=uid,
                task_id=tid,
                events=writes,
                session=session,
            )
            await session.commit()
            return next_seq

    res = await session.execute(select(Task).where(Task.id == tid, Task.user_id == uid))
    task = res.scalar_one_or_none()
    if not task:
        raise ValueError("task_not_found")

    current_seq = int(task.last_seq or 0)
    max_seq = current_seq
    latest_progress: Optional[float] = None

    for write in writes:
        if isinstance(write, dict):
            event_type = str(write.get("event_type") or "").strip() or "event"
            payload = write.get("payload") if isinstance(write.get("payload"), dict) else {}
            progress = write.get("progress")
            seq = write.get("seq")
        else:
            event_type = str(getattr(write, "event_type", "") or "").strip() or "event"
            payload = getattr(write, "payload", {})
            if not isinstance(payload, dict):
                payload = {}
            progress = getattr(write, "progress", None)
            seq = getattr(write, "seq", None)
        if seq is None:
            seq = max_seq + 1
        seq = int(seq or 0)
        if seq <= 0:
            seq = max_seq + 1
        max_seq = max(max_seq, seq)

        evt = TaskEvent(
            task_id=tid,
            seq=seq,
            event_type=event_type,
            payload_json=_json_dumps(payload, default="{}"),
        )
        session.add(evt)
        if progress is not None:
            latest_progress = float(progress or 0.0)

    task.last_seq = max(int(task.last_seq or 0), max_seq)
    if latest_progress is not None:
        task.progress = latest_progress
    task.updated_at = utcnow_naive()
    session.add(task)

    await session.flush()
    return max_seq


async def append_task_event(
    *,
    user_id: str,
    task_id: str,
    event_type: str,
    payload: Dict[str, Any],
    seq: Optional[int] = None,
    progress: Optional[float] = None,
    session: Optional[AsyncSession] = None,
) -> int:
    return await append_task_events(
        user_id=user_id,
        task_id=task_id,
        events=[{"event_type": event_type, "payload": payload, "seq": seq, "progress": progress}],
        session=session,
    )


async def list_tasks(
    *,
    user_id: str,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_tasks(
                user_id=uid,
                status=status,
                task_type=task_type,
                limit=limit,
                offset=offset,
                session=session,
            )

    where = [Task.user_id == uid]
    if status:
        where.append(Task.status == str(status).strip())
    if task_type:
        where.append(Task.task_type == str(task_type).strip())

    stmt = select(Task).where(and_(*where)).order_by(Task.updated_at.desc()).limit(int(limit or 50)).offset(int(offset))
    result = await session.execute(stmt)
    items = result.scalars().all()
    return [_task_to_dict(t, include_payloads=False) for t in items]


async def get_task(
    *,
    user_id: str,
    task_id: str,
    include_events: bool = False,
    events_limit: int = 200,
    events_after_seq: int = 0,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    tid = str(task_id or "").strip()
    if not tid:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_task(
                user_id=uid,
                task_id=tid,
                include_events=include_events,
                events_limit=events_limit,
                events_after_seq=events_after_seq,
                session=session,
            )

    res = await session.execute(select(Task).where(Task.id == tid, Task.user_id == uid))
    task = res.scalar_one_or_none()
    if not task:
        return None

    out = _task_to_dict(task)
    if include_events:
        limit_safe = max(1, min(int(events_limit or 200), 5000))
        requested_after_seq = max(0, int(events_after_seq or 0))
        after_seq = requested_after_seq if requested_after_seq > 0 else max(0, int(task.last_seq or 0) - limit_safe)
        events = await list_task_events(
            user_id=uid,
            task_id=tid,
            after_seq=after_seq,
            limit=limit_safe,
            session=session,
        )
        out["events"] = events
    return out


async def list_task_events(
    *,
    user_id: str,
    task_id: str,
    after_seq: int = 0,
    limit: int = 200,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    tid = str(task_id or "").strip()
    if not tid:
        return []

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_task_events(user_id=uid, task_id=tid, after_seq=after_seq, limit=limit, session=session)

    res = await session.execute(select(Task.id).where(Task.id == tid, Task.user_id == uid))
    if not res.scalar_one_or_none():
        return []

    limit_safe = max(1, min(int(limit or 200), 5000))
    stmt = (
        select(TaskEvent)
        .where(TaskEvent.task_id == tid, TaskEvent.seq > int(after_seq or 0))
        .order_by(TaskEvent.seq.asc())
        .limit(limit_safe)
    )
    result = await session.execute(stmt)
    items = result.scalars().all()
    return [_event_to_dict(e) for e in items]


async def average_duration_seconds(
    *,
    user_id: str,
    task_type: str,
    sample: int = 50,
    session: Optional[AsyncSession] = None,
) -> Optional[float]:
    uid = _require_user_id(user_id)
    ttype = str(task_type or "").strip()
    if not ttype:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await average_duration_seconds(user_id=uid, task_type=ttype, sample=sample, session=session)

    aggregate_res = await session.execute(
        select(TaskDurationAggregate).where(TaskDurationAggregate.task_type == ttype)
    )
    aggregate = aggregate_res.scalar_one_or_none()
    if aggregate is not None and int(aggregate.completed_count or 0) > 0:
        ema = float(aggregate.duration_ema_seconds or 0.0)
        if ema > 0:
            return ema
        total = float(aggregate.duration_sum_seconds or 0.0)
        if total > 0:
            return total / max(1, int(aggregate.completed_count or 0))

    stmt = (
        select(Task.started_at, Task.ended_at)
        .where(
            Task.user_id == uid,
            Task.task_type == ttype,
            Task.status == "completed",
            Task.started_at.is_not(None),
            Task.ended_at.is_not(None),
        )
        .order_by(Task.ended_at.desc())
        .limit(int(sample or 50))
    )
    res = await session.execute(stmt)
    rows = res.all()

    durations: List[float] = []
    for started_at, ended_at in rows:
        try:
            if started_at and ended_at:
                durations.append((ended_at - started_at).total_seconds())
        except (OverflowError, TypeError, ValueError):
            continue

    if not durations:
        return None
    return sum(durations) / len(durations)


async def fail_running_tasks_on_startup(
    *,
    reason: str = "server_restarted",
    limit: int = 5000,
    session: Optional[AsyncSession] = None,
) -> int:
    """Mark tasks left in `running` as failed after a process restart.

    The system stores long-running workflows (study materials, question library,
    exports, etc.) in the unified `tasks` table. If the process stops mid-run,
    rows may remain stuck at `running`. On the next startup we fail them so:
    - `/api/tasks/*` doesn't show ghost running jobs forever
    - SSE pollers that replay `task_events` can terminate cleanly
    """

    own = session is None
    if own:
        async with async_session_maker() as session:
            changed = await fail_running_tasks_on_startup(reason=reason, limit=limit, session=session)
            await session.commit()
            return changed

    now = utcnow_naive()
    try:
        limit_n = int(limit or 0)
    except (TypeError, ValueError):
        limit_n = 5000
    limit_n = max(1, min(limit_n, 50_000))

    res = await session.execute(select(Task).where(Task.status == "running").limit(limit_n))
    running = list(res.scalars().all())
    if not running:
        return 0

    changed = 0
    for task in running:
        task_id = str(task.id or "").strip()
        user_id = str(task.user_id or "").strip()
        task_type = str(task.task_type or "").strip()
        if not task_id or not user_id:
            continue

        message = "Task aborted due to server restart."
        terminal_reason = str(reason or "server_restarted").strip() or "server_restarted"
        if task_type == "study_materials":
            message = (
                "Server restarted; this task can no longer stream. You can start a new task or continue if resumable."
            )
        elif task_type.startswith("question_library"):
            terminal_reason = "interrupted"
            message = "Server restarted; question-library generation interrupted. You can start a new session."

        # Update terminal status first so pollers observe a stable snapshot even if
        # we fail to insert the final event.
        task.status = "failed"
        task.ended_at = now
        task.updated_at = now
        task.error_json = _json_dumps(
            {"message": terminal_reason, "reason": str(reason or "server_restarted"), "task_type": task_type},
            default="{}",
        )
        session.add(task)

        try:
            await append_task_event(
                user_id=user_id,
                task_id=task_id,
                event_type="warning",
                payload={
                    "message": message,
                    "reason": terminal_reason,
                    "task_type": task_type,
                },
                seq=None,
                progress=float(task.progress or 0.0),
                session=session,
            )
        except Exception:
            # Best-effort: never block startup on event write failures.
            logger.warning(
                "task_restart_warning_event_write_failed",
                extra={"user_id": user_id, "task_id": task_id, "task_type": task_type},
                exc_info=True,
            )
        changed += 1

    await session.flush()
    return changed
