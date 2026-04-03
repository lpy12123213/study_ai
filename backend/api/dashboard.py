from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.database.engine import async_session_maker
from backend.database.schema import GeneratedFile, Task

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_auth)])
logger = get_logger(__name__)


def _parse_iso_date(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _window(from_iso: Optional[str], to_iso: Optional[str], days: int) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    dt_to = _parse_iso_date(to_iso or "") or now
    dt_from = _parse_iso_date(from_iso or "")
    if dt_from is None:
        days = max(1, min(int(days or 30), 365))
        dt_from = dt_to - timedelta(days=days)
    if dt_from > dt_to:
        dt_from, dt_to = dt_to - timedelta(days=1), dt_to
    return dt_from, dt_to


def _extract_subject(request: dict) -> str:
    if not isinstance(request, dict):
        return ""
    for key in ("subject", "Subject"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:100]
    return ""


@router.get("/stats", response_model=dict)
async def get_dashboard_stats(
    days: int = Query(30, ge=1, le=365),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    dt_from, dt_to = _window(from_, to, days)

    async with async_session_maker() as session:
        res = await session.execute(
            select(Task).where(
                Task.user_id == user_id,
                Task.created_at >= dt_from.replace(tzinfo=None),
                Task.created_at <= dt_to.replace(tzinfo=None),
            )
        )
        tasks = res.scalars().all()

        gen_res = await session.execute(
            select(GeneratedFile).where(
                GeneratedFile.user_id == user_id,
                GeneratedFile.created_at >= dt_from.replace(tzinfo=None),
                GeneratedFile.created_at <= dt_to.replace(tzinfo=None),
            )
        )
        generated = gen_res.scalars().all()

    tasks_total = len(tasks)
    tasks_by_type: Dict[str, int] = {}
    tasks_by_status: Dict[str, int] = {}
    subjects: Dict[str, int] = {}

    durations: list[float] = []
    for t in tasks:
        ttype = str(t.task_type or "").strip() or "unknown"
        tasks_by_type[ttype] = int(tasks_by_type.get(ttype, 0)) + 1
        status = str(t.status or "").strip() or "unknown"
        tasks_by_status[status] = int(tasks_by_status.get(status, 0)) + 1

        try:
            parsed = json.loads(str(t.request_json or "{}"))
            subj = _extract_subject(parsed if isinstance(parsed, dict) else {})
            if subj:
                subjects[subj] = int(subjects.get(subj, 0)) + 1
        except Exception:
            pass

        if t.started_at and t.ended_at:
            try:
                durations.append(max(0.0, (t.ended_at - t.started_at).total_seconds()))
            except Exception:
                pass

    terminal = sum(tasks_by_status.get(s, 0) for s in ("completed", "failed", "canceled"))
    completed = int(tasks_by_status.get("completed", 0))
    completion_rate = float(completed / terminal) if terminal else 0.0

    avg_duration_s = float(sum(durations) / len(durations)) if durations else 0.0

    exports_total = len(generated)
    exports_by_type: Dict[str, int] = {}
    for g in generated:
        ftype = str(g.file_type or "").strip() or "unknown"
        exports_by_type[ftype] = int(exports_by_type.get(ftype, 0)) + 1

    top_subjects = sorted(subjects.items(), key=lambda kv: (-kv[1], kv[0]))[:10]

    return {
        "from": dt_from.isoformat(),
        "to": dt_to.isoformat(),
        "tasks_total": tasks_total,
        "tasks_by_type": tasks_by_type,
        "tasks_by_status": tasks_by_status,
        "completion_rate": completion_rate,
        "avg_duration_s": avg_duration_s,
        "exports_total": exports_total,
        "exports_by_type": exports_by_type,
        "top_subjects": [{"subject": k, "count": v} for k, v in top_subjects],
    }


@router.get("/export", response_model=None)
async def export_dashboard_csv(
    days: int = Query(30, ge=1, le=365),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
) -> Response:
    stats = await get_dashboard_stats(days=days, from_=from_, to=to, user=user)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["metric", "value"])
    w.writerow(["from", stats.get("from")])
    w.writerow(["to", stats.get("to")])
    w.writerow(["tasks_total", stats.get("tasks_total")])
    w.writerow(["completion_rate", stats.get("completion_rate")])
    w.writerow(["avg_duration_s", stats.get("avg_duration_s")])
    w.writerow(["exports_total", stats.get("exports_total")])
    for key, value in sorted((stats.get("tasks_by_type") or {}).items()):
        w.writerow([f"tasks_by_type.{key}", value])
    for key, value in sorted((stats.get("tasks_by_status") or {}).items()):
        w.writerow([f"tasks_by_status.{key}", value])
    for row in stats.get("top_subjects") or []:
        w.writerow([f"top_subject.{row.get('subject')}", row.get("count")])

    content = buf.getvalue()
    filename = f"dashboard-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.csv"
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
