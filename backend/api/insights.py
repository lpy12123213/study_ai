from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from backend.api.auth import require_auth
from backend.api.dashboard import _window
from backend.database.engine import async_session_maker
from backend.database.repositories.analytics.insights import get_insights_overview as load_insights_overview

router = APIRouter(prefix="/insights", tags=["insights"], dependencies=[Depends(require_auth)])


def _user_id(user: dict) -> str:
    uid = str((user or {}).get("user_id") or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return uid


async def _overview_payload(
    *,
    days: int,
    from_: Optional[str],
    to: Optional[str],
    subject: Optional[str],
    user: dict,
) -> dict:
    uid = _user_id(user)
    dt_from, dt_to = _window(from_, to, days)
    normalized_subject = str(subject or "").strip() or None
    async with async_session_maker() as session:
        overview = await load_insights_overview(
            session,
            user_id=uid,
            dt_from=dt_from,
            dt_to=dt_to,
            subject=normalized_subject,
        )
    return {
        "from": dt_from.isoformat(),
        "to": dt_to.isoformat(),
        "subject": normalized_subject or "",
        **overview,
    }


@router.get("/overview", response_model=dict)
async def get_insights_overview(
    days: int = Query(30, ge=1, le=365),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
) -> dict:
    return await _overview_payload(days=days, from_=from_, to=to, subject=subject, user=user)


def _flatten(prefix: str, value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten(child_prefix, child)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, dict):
                label = (
                    child.get("date")
                    or child.get("question_type")
                    or child.get("essay_type")
                    or child.get("bucket")
                    or child.get("knowledge_point")
                    or child.get("session_id")
                    or index
                )
                yield from _flatten(f"{prefix}.{label}", child)
            else:
                yield (f"{prefix}.{index}", child)
        return
    yield (prefix, value)


@router.get("/export", response_model=None)
async def export_insights_csv(
    days: int = Query(30, ge=1, le=365),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
) -> Response:
    overview = await _overview_payload(days=days, from_=from_, to=to, subject=subject, user=user)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["metric", "value"])
    for metric, value in _flatten("", overview):
        writer.writerow([metric, value])

    filename = f"insights-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.csv"
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
