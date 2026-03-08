from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.schema import Task, TaskEvent


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
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return default


def _json_loads(value: str, *, default: Any) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _task_to_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "user_id": task.user_id,
        "task_type": task.task_type,
        "title": task.title,
        "status": task.status,
        "progress": float(task.progress or 0.0),
        "last_seq": int(task.last_seq or 0),
        "parent_task_id": task.parent_task_id,
        "request": _json_loads(task.request_json, default={}),
        "result": _json_loads(task.result_json, default={}),
        "error": _json_loads(task.error_json, default={}),
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "updated_at": task.updated_at.isoformat() if task.updated_at else "",
        "started_at": task.started_at.isoformat() if task.started_at else "",
        "ended_at": task.ended_at.isoformat() if task.ended_at else "",
    }


def _event_to_dict(evt: TaskEvent) -> dict:
    return {
        "taskId": evt.task_id,
        "seq": int(evt.seq or 0),
        "type": evt.event_type,
        "data": _json_loads(evt.payload_json, default={}),
        "created_at": evt.created_at.isoformat() if evt.created_at else "",
    }


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
    await session.flush()
    return True


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
    uid = _require_user_id(user_id)
    tid = str(task_id or "").strip()
    if not tid:
        raise ValueError("missing_task_id")

    own = session is None
    if own:
        async with async_session_maker() as session:
            next_seq = await append_task_event(
                user_id=uid,
                task_id=tid,
                event_type=event_type,
                payload=payload,
                seq=seq,
                progress=progress,
                session=session,
            )
            await session.commit()
            return next_seq

    res = await session.execute(select(Task).where(Task.id == tid, Task.user_id == uid))
    task = res.scalar_one_or_none()
    if not task:
        raise ValueError("task_not_found")

    if seq is None:
        seq = int(task.last_seq or 0) + 1
    seq = int(seq or 0)
    if seq <= 0:
        seq = int(task.last_seq or 0) + 1

    evt = TaskEvent(
        task_id=tid,
        seq=seq,
        event_type=str(event_type or "").strip() or "event",
        payload_json=_json_dumps(payload, default="{}"),
    )
    session.add(evt)

    task.last_seq = max(int(task.last_seq or 0), seq)
    if progress is not None:
        task.progress = float(progress or 0.0)
    task.updated_at = datetime.utcnow()
    session.add(task)

    await session.flush()
    return seq


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
    return [_task_to_dict(t) for t in items]


async def get_task(
    *,
    user_id: str,
    task_id: str,
    include_events: bool = False,
    events_limit: int = 500,
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
                session=session,
            )

    res = await session.execute(select(Task).where(Task.id == tid, Task.user_id == uid))
    task = res.scalar_one_or_none()
    if not task:
        return None

    out = _task_to_dict(task)
    if include_events:
        events = await list_task_events(
            user_id=uid,
            task_id=tid,
            after_seq=max(0, int(task.last_seq or 0) - int(events_limit or 500)),
            limit=events_limit,
            session=session,
        )
        out["events"] = events
    return out


async def list_task_events(
    *,
    user_id: str,
    task_id: str,
    after_seq: int = 0,
    limit: int = 2000,
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

    stmt = (
        select(TaskEvent)
        .where(TaskEvent.task_id == tid, TaskEvent.seq > int(after_seq or 0))
        .order_by(TaskEvent.seq.asc())
        .limit(int(limit or 2000))
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
        except Exception:
            continue

    if not durations:
        return None
    return sum(durations) / len(durations)
