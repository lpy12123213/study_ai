from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.database.models import get_paper as db_get_paper
from backend.database.repositories.study_archives import get_study_archive as db_get_study_archive
from backend.database.repositories.tasks import (
    append_task_event as db_append_task_event,
)
from backend.database.repositories.tasks import (
    average_duration_seconds as db_average_duration_seconds,
)
from backend.database.repositories.tasks import (
    get_task as db_get_task,
)
from backend.database.repositories.tasks import (
    list_task_events as db_list_task_events,
)
from backend.database.repositories.tasks import (
    list_tasks as db_list_tasks,
)
from backend.database.repositories.tasks import (
    update_task_status as db_update_task_status,
)
from backend.database.repositories.tasks import (
    upsert_task as db_upsert_task,
)
from backend.deepthink_service import deepthink_service
from backend.lesson_plan_agent_v2 import generate_lesson_plan_stream
from backend.media.generated import default_generated_media_ttl_s, publish_generated_text
from backend.paper_compose.compose_tasks import compose_tasks
from backend.paper_compose.export import export_paper as export_paper_doc
from backend.paper_compose.task_manager import PaperComposeTask
from backend.paper_compose.workflow import compose_paper_events
from backend.study_materials.tasks_singleton import study_material_tasks

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(require_auth)])
logger = get_logger(__name__)


def _sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


_background_runners: dict[str, asyncio.Task] = {}


def _track_background_runner(task_id: str, runner: asyncio.Task) -> None:
    tid = str(task_id or "").strip()
    if not tid:
        return
    _background_runners[tid] = runner

    def _cleanup(_: asyncio.Task) -> None:
        _background_runners.pop(tid, None)

    runner.add_done_callback(_cleanup)


def _cancel_background_runner(task_id: str) -> None:
    tid = str(task_id or "").strip()
    if not tid:
        return
    runner = _background_runners.get(tid)
    if runner and not runner.done():
        runner.cancel()


async def _get_db_task_status(*, user_id: str, task_id: str) -> str:
    try:
        task = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
    except Exception:
        return ""
    if not task:
        return ""
    return str(task.get("status") or "").strip()


async def _run_export_paper_task(*, user_id: str, task_id: str, request: dict) -> None:
    try:
        paper_id = int(request.get("paper_id") or request.get("paperId") or 0)
    except Exception:
        paper_id = 0
    fmt = str(request.get("format") or request.get("fmt") or "markdown").strip().lower()
    include_stem = bool(request.get("include_stem") or request.get("includeStem"))
    include_answer = bool(request.get("include_answer") or request.get("includeAnswer"))
    include_analysis = bool(request.get("include_analysis") or request.get("includeAnalysis"))

    paper = None
    if paper_id > 0:
        try:
            paper = await db_get_paper(user_id=user_id, paper_id=paper_id)
        except Exception:
            paper = None

    if not paper:
        await db_append_task_event(
            user_id=user_id,
            task_id=task_id,
            event_type="error",
            payload={"error": {"code": "paper_not_found", "message": "试卷不存在"}},
        )
        await _emit_db_task_terminal(
            user_id=user_id, task_id=task_id, status="failed", error={"message": "paper_not_found"}
        )
        return

    await db_append_task_event(
        user_id=user_id,
        task_id=task_id,
        event_type="progress",
        payload={"progress": 10.0},
        progress=10.0,
    )

    try:
        out = await export_paper_doc(
            paper,
            user_id=user_id,
            fmt=fmt,
            include_stem=include_stem,
            include_answer=include_answer,
            include_analysis=include_analysis,
        )
    except asyncio.CancelledError:
        await _emit_db_task_terminal(
            user_id=user_id, task_id=task_id, status="canceled", error={"message": "Task cancelled"}
        )
        raise
    except ValueError as exc:
        await db_append_task_event(
            user_id=user_id,
            task_id=task_id,
            event_type="error",
            payload={"error": {"code": "export_invalid_request", "message": str(exc)}},
        )
        await _emit_db_task_terminal(user_id=user_id, task_id=task_id, status="failed", error={"message": str(exc)})
        return
    except Exception as exc:  # pragma: no cover
        await db_append_task_event(
            user_id=user_id,
            task_id=task_id,
            event_type="error",
            payload={"error": {"code": "export_failed", "message": str(exc)}},
        )
        await _emit_db_task_terminal(user_id=user_id, task_id=task_id, status="failed", error={"message": str(exc)})
        return

    await db_append_task_event(
        user_id=user_id,
        task_id=task_id,
        event_type="progress",
        payload={"progress": 95.0},
        progress=95.0,
    )

    if isinstance(out, dict) and out.get("success") is False:
        err_code = str(out.get("error") or "export_failed").strip() or "export_failed"
        await db_append_task_event(
            user_id=user_id,
            task_id=task_id,
            event_type="error",
            payload={"error": {"code": err_code, "message": err_code, "detail": out}},
        )
        await _emit_db_task_terminal(
            user_id=user_id, task_id=task_id, status="failed", error={"message": err_code, "detail": out}
        )
        return

    result = dict(out) if isinstance(out, dict) else {"result": out}
    result["paper_id"] = paper_id
    await _emit_db_task_terminal(user_id=user_id, task_id=task_id, status="completed", result=result)


async def _run_export_study_archive_task(*, user_id: str, task_id: str, request: dict) -> None:
    try:
        archive_id = int(request.get("archive_id") or request.get("archiveId") or 0)
    except Exception:
        archive_id = 0
    fmt = str(request.get("format") or request.get("fmt") or "markdown").strip().lower()
    if fmt not in {"md", "markdown"}:
        await db_append_task_event(
            user_id=user_id,
            task_id=task_id,
            event_type="error",
            payload={"error": {"code": "unsupported_format", "message": "unsupported_format"}},
        )
        await _emit_db_task_terminal(
            user_id=user_id, task_id=task_id, status="failed", error={"message": "unsupported_format"}
        )
        return

    archive = None
    if archive_id > 0:
        try:
            archive = await db_get_study_archive(user_id=user_id, archive_id=archive_id)
        except Exception:
            archive = None
    if not archive:
        await _emit_db_task_terminal(
            user_id=user_id, task_id=task_id, status="failed", error={"message": "study_archive_not_found"}
        )
        return

    markdown = str(archive.get("markdown") or "").strip()
    if not markdown:
        markdown = f"# {str(archive.get('topic') or '自学资料').strip()}\n\n（无内容）\n"

    await db_append_task_event(
        user_id=user_id,
        task_id=task_id,
        event_type="progress",
        payload={"progress": 30.0},
        progress=30.0,
    )

    try:
        out = await publish_generated_text(
            markdown,
            user_id=user_id,
            ext=".md",
            file_type="md",
            mime_type="text/markdown; charset=utf-8",
            ttl_s=default_generated_media_ttl_s(),
        )
    except asyncio.CancelledError:
        await _emit_db_task_terminal(
            user_id=user_id, task_id=task_id, status="canceled", error={"message": "Task cancelled"}
        )
        raise
    except Exception as exc:  # pragma: no cover
        await _emit_db_task_terminal(user_id=user_id, task_id=task_id, status="failed", error={"message": str(exc)})
        return

    result = {"format": "markdown", "archive_id": archive_id, **(out if isinstance(out, dict) else {"result": out})}
    await _emit_db_task_terminal(user_id=user_id, task_id=task_id, status="completed", result=result)


async def _run_deepthink_task(*, user_id: str, task_id: str, request: Dict[str, Any]) -> None:
    uid = str(user_id or "").strip()
    tid = str(task_id or "").strip()
    if not uid or not tid:
        return

    question = str((request or {}).get("question") or "").strip()
    subject = str((request or {}).get("subject") or "高中数学").strip() or "高中数学"
    image_url = (request or {}).get("image_url")

    try:
        async for event in deepthink_service.solve(question=question, subject=subject, image_url=image_url):
            status = await _get_db_task_status(user_id=uid, task_id=tid)
            if status and status != "running":
                return

            kind = str((event or {}).get("type") or "event").strip() or "event"
            payload = dict(event or {}) if isinstance(event, dict) else {"event": event}
            await db_append_task_event(user_id=uid, task_id=tid, event_type=kind, payload=payload)

            if kind == "done":
                await db_update_task_status(
                    user_id=uid,
                    task_id=tid,
                    status="completed",
                    progress=100.0,
                    result=payload if isinstance(payload, dict) else {"result": payload},
                    ended_at=datetime.utcnow(),
                )
                return
            if kind == "error":
                msg = str(payload.get("message") or payload.get("error") or "deepthink_failed").strip()
                await db_update_task_status(
                    user_id=uid,
                    task_id=tid,
                    status="failed",
                    error={"message": msg},
                    ended_at=datetime.utcnow(),
                )
                return
    except asyncio.CancelledError:
        status = await _get_db_task_status(user_id=uid, task_id=tid)
        if status in {"paused", "canceled", "cancelled"}:
            raise
        try:
            await db_update_task_status(
                user_id=uid,
                task_id=tid,
                status="canceled",
                error={"message": "Task cancelled"},
                ended_at=datetime.utcnow(),
            )
        except Exception:
            logger.exception("deepthink_task_cancel_write_failed", extra={"task_id": tid, "user_id": uid})
        raise
    except Exception as exc:
        try:
            await db_update_task_status(
                user_id=uid,
                task_id=tid,
                status="failed",
                error={"message": str(exc)},
                ended_at=datetime.utcnow(),
            )
        except Exception:
            logger.exception("deepthink_task_error_write_failed", extra={"task_id": tid, "user_id": uid})


async def _run_lesson_plan_task(*, user_id: str, task_id: str, request: Dict[str, Any]) -> None:
    uid = str(user_id or "").strip()
    tid = str(task_id or "").strip()
    if not uid or not tid:
        return

    try:
        async for event in generate_lesson_plan_stream(
            subject=str((request or {}).get("subject") or "").strip(),
            grade=str((request or {}).get("grade") or "").strip(),
            topic=str((request or {}).get("topic") or "").strip(),
            user_id=uid,
            duration_minutes=(request or {}).get("duration_minutes"),
            objectives=(request or {}).get("objectives"),
            teaching_style=(request or {}).get("teaching_style"),
            student_level=(request or {}).get("student_level"),
            additional_requirements=(request or {}).get("additional_requirements"),
        ):
            status = await _get_db_task_status(user_id=uid, task_id=tid)
            if status and status != "running":
                return

            kind = str((event or {}).get("event") or "").strip() or "event"
            data = (event or {}).get("data") if isinstance((event or {}).get("data"), dict) else {}
            await db_append_task_event(user_id=uid, task_id=tid, event_type=kind, payload=data)

            if kind == "done":
                material = data.get("material") if isinstance(data, dict) else {}
                await db_update_task_status(
                    user_id=uid,
                    task_id=tid,
                    status="completed",
                    progress=100.0,
                    result=material if isinstance(material, dict) else {"material": material},
                    ended_at=datetime.utcnow(),
                )
                return
            if kind == "error":
                msg = str((data or {}).get("message") or "lesson_plan_failed").strip()
                await db_update_task_status(
                    user_id=uid,
                    task_id=tid,
                    status="failed",
                    error={"message": msg},
                    ended_at=datetime.utcnow(),
                )
                return
    except asyncio.CancelledError:
        status = await _get_db_task_status(user_id=uid, task_id=tid)
        if status in {"paused", "canceled", "cancelled"}:
            raise
        try:
            await db_update_task_status(
                user_id=uid,
                task_id=tid,
                status="canceled",
                error={"message": "Task cancelled"},
                ended_at=datetime.utcnow(),
            )
        except Exception:
            logger.exception("lesson_plan_task_cancel_write_failed", extra={"task_id": tid, "user_id": uid})
        raise
    except Exception as exc:
        try:
            await db_update_task_status(
                user_id=uid,
                task_id=tid,
                status="failed",
                error={"message": str(exc)},
                ended_at=datetime.utcnow(),
            )
        except Exception:
            logger.exception("lesson_plan_task_error_write_failed", extra={"task_id": tid, "user_id": uid})


async def _emit_db_task_started(*, user_id: str, task_id: str, task_type: str, title: str, request: dict) -> None:
    await db_upsert_task(
        user_id=user_id,
        task_id=task_id,
        task_type=task_type,
        title=title,
        status="running",
        progress=0.0,
        request=request,
        started_at=datetime.utcnow(),
    )
    await db_append_task_event(
        user_id=user_id,
        task_id=task_id,
        event_type="step",
        payload={
            "step": {
                "id": "task_started",
                "title": "任务开始",
                "status": "running",
                "startTime": _now_iso(),
                "toolName": task_type,
                "input": request,
            }
        },
    )


async def _emit_db_task_terminal(
    *,
    user_id: str,
    task_id: str,
    status: str,
    result: Optional[dict] = None,
    error: Optional[dict] = None,
) -> None:
    ended_at = datetime.utcnow()
    await db_update_task_status(
        user_id=user_id,
        task_id=task_id,
        status=status,
        progress=100.0 if status == "completed" else None,
        result=result,
        error=error,
        ended_at=ended_at,
    )


@router.get("", response_model=dict)
async def list_tasks(
    status: Optional[str] = Query(None),
    task_type: Optional[str] = Query(None, alias="type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10_000),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    items = await db_list_tasks(user_id=user_id, status=status, task_type=task_type, limit=limit, offset=offset)

    # Compute coarse ETA based on per-type historical averages (best-effort).
    averages: Dict[str, Optional[float]] = {}
    now = time.time()
    for t in items:
        if str(t.get("status") or "") != "running":
            continue
        ttype = str(t.get("task_type") or "").strip()
        if not ttype:
            continue
        if ttype not in averages:
            averages[ttype] = await db_average_duration_seconds(user_id=user_id, task_type=ttype, sample=50)

        started_at = str(t.get("started_at") or "").strip()
        try:
            started_ts = datetime.fromisoformat(started_at.replace("Z", "+00:00")).timestamp() if started_at else None
        except Exception:
            started_ts = None
        if not started_ts:
            continue

        elapsed_s = max(0.0, now - started_ts)
        avg_s = averages.get(ttype)
        if avg_s and avg_s > 1:
            t["elapsed_s"] = elapsed_s
            t["eta_s"] = max(0.0, float(avg_s) - elapsed_s)

    return {"tasks": items, "count": len(items)}


@router.get("/{task_id}", response_model=dict)
async def get_task_status(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    db_task = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
    if not db_task:
        # Back-compat: in-memory compose task payload (legacy shape).
        payload = await compose_tasks.status_payload(task_id=task_id, user_id=user_id)
        if payload:
            return payload
        raise HTTPException(status_code=404, detail="task_not_found")

    if str(db_task.get("status") or "") == "running":
        ttype = str(db_task.get("task_type") or "").strip()
        started_at = str(db_task.get("started_at") or "").strip()
        try:
            started_ts = datetime.fromisoformat(started_at.replace("Z", "+00:00")).timestamp() if started_at else None
        except Exception:
            started_ts = None
        if ttype and started_ts:
            try:
                avg_s = await db_average_duration_seconds(user_id=user_id, task_type=ttype, sample=50)
                if avg_s and avg_s > 1:
                    now = time.time()
                    elapsed_s = max(0.0, now - started_ts)
                    db_task["elapsed_s"] = elapsed_s
                    db_task["eta_s"] = max(0.0, float(avg_s) - elapsed_s)
            except Exception:
                logger.debug(
                    "task_eta_compute_failed",
                    extra={"task_id": task_id, "user_id": user_id, "task_type": ttype},
                    exc_info=True,
                )
    return db_task


@router.post("/{task_id}/pause", response_model=dict)
async def pause_task(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await compose_tasks.pause_task(task_id=task_id, user_id=user_id)
    if ok:
        try:
            await db_update_task_status(user_id=user_id, task_id=task_id, status="paused")
            await db_append_task_event(
                user_id=user_id,
                task_id=task_id,
                event_type="step",
                payload={
                    "step": {"id": "task_paused", "title": "任务已暂停", "status": "paused", "startTime": _now_iso()}
                },
            )
        except Exception:
            logger.exception("task_pause_db_sync_failed", extra={"task_id": task_id, "user_id": user_id})
        return {"success": True}

    ok = await study_material_tasks.pause_task(task_id=task_id, user_id=user_id)
    if ok:
        return {"success": True}

    # Fallback: DB tasks only (cooperative pause via status).
    db_task = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
    if not db_task:
        raise HTTPException(status_code=404, detail="task_not_found")

    await db_update_task_status(user_id=user_id, task_id=task_id, status="paused")
    await db_append_task_event(
        user_id=user_id,
        task_id=task_id,
        event_type="step",
        payload={"step": {"id": "task_paused", "title": "任务已暂停", "status": "paused", "startTime": _now_iso()}},
    )
    _cancel_background_runner(task_id)
    return {"success": True}


@router.post("/{task_id}/resume", response_model=dict)
async def resume_task(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    async def runner_factory(task: PaperComposeTask):
        await _emit_db_task_started(
            user_id=user_id,
            task_id=task.task_id,
            task_type="paper_compose",
            title=str((task.request or {}).get("paperName") or (task.request or {}).get("paper_name") or "组卷任务"),
            request=dict(task.request or {}),
        )
        try:
            async for evt in compose_paper_events(task.request, user_id=user_id):
                if task.status != "running":
                    break
                await compose_tasks.append_event(task, evt)
                try:
                    payload = {k: evt.get(k) for k in ("step", "progress", "result", "error", "message") if k in evt}
                    progress = None
                    if "progress" in payload:
                        try:
                            progress = float(payload.get("progress") or 0.0)
                        except Exception:
                            progress = None
                    await db_append_task_event(
                        user_id=user_id,
                        task_id=task.task_id,
                        event_type=str(evt.get("type") or "event"),
                        payload=payload,
                        seq=None,
                        progress=progress,
                    )
                except Exception:
                    logger.exception(
                        "task_compose_event_write_failed",
                        extra={"task_id": task.task_id, "user_id": user_id, "event": evt},
                    )
                kind = str(evt.get("type") or "")
                if kind == "result":
                    await compose_tasks.complete_task(task)
                    try:
                        result = (
                            evt.get("result") if isinstance(evt.get("result"), dict) else {"result": evt.get("result")}
                        )
                        await _emit_db_task_terminal(
                            user_id=user_id, task_id=task.task_id, status="completed", result=result
                        )
                    except Exception:
                        logger.exception(
                            "task_compose_complete_write_failed", extra={"task_id": task.task_id, "user_id": user_id}
                        )
                    return
                if kind == "error":
                    await compose_tasks.fail_task(task, str(evt.get("error") or "compose_failed"))
                    try:
                        await _emit_db_task_terminal(
                            user_id=user_id,
                            task_id=task.task_id,
                            status="failed",
                            error={
                                "message": str(evt.get("error") or "compose_failed"),
                                "code": str(evt.get("error") or "compose_failed"),
                            },
                        )
                    except Exception:
                        logger.exception(
                            "task_compose_fail_write_failed", extra={"task_id": task.task_id, "user_id": user_id}
                        )
                    return
        except asyncio.CancelledError:
            await compose_tasks.fail_task(task, "Task cancelled")
            try:
                await _emit_db_task_terminal(
                    user_id=user_id,
                    task_id=task.task_id,
                    status="canceled",
                    error={"message": "Task cancelled"},
                )
            except Exception:
                logger.exception(
                    "task_compose_cancel_write_failed", extra={"task_id": task.task_id, "user_id": user_id}
                )
            raise
        except Exception as exc:  # pragma: no cover
            await compose_tasks.fail_task(task, str(exc))
            try:
                await _emit_db_task_terminal(
                    user_id=user_id, task_id=task.task_id, status="failed", error={"message": str(exc)}
                )
            except Exception:
                logger.exception("task_compose_error_write_failed", extra={"task_id": task.task_id, "user_id": user_id})
        finally:
            if task.status == "running":
                await compose_tasks.fail_task(task, "Task ended unexpectedly")
                try:
                    await _emit_db_task_terminal(
                        user_id=user_id,
                        task_id=task.task_id,
                        status="failed",
                        error={"message": "Task ended unexpectedly"},
                    )
                except Exception:
                    logger.exception(
                        "task_compose_final_write_failed", extra={"task_id": task.task_id, "user_id": user_id}
                    )

    ok = await compose_tasks.resume_task(task_id=task_id, user_id=user_id, runner_factory=runner_factory)
    if ok:
        return {"success": True}

    ok = await study_material_tasks.resume_task(task_id=task_id, user_id=user_id)
    if ok:
        return {"success": True}

    db_task = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
    if not db_task:
        raise HTTPException(status_code=404, detail="task_not_found")

    status = str(db_task.get("status") or "").strip()
    task_type = str(db_task.get("task_type") or "").strip()
    if status == "running":
        return {"success": True}
    if status != "paused":
        raise HTTPException(status_code=400, detail="task_not_resumable")

    req = db_task.get("request") if isinstance(db_task.get("request"), dict) else {}

    if task_type == "deepthink":
        await db_update_task_status(user_id=user_id, task_id=task_id, status="running", progress=0.0, error={})
        await db_append_task_event(
            user_id=user_id,
            task_id=task_id,
            event_type="step",
            payload={
                "step": {"id": "task_resumed", "title": "任务继续执行", "status": "running", "startTime": _now_iso()}
            },
        )
        _cancel_background_runner(task_id)
        runner = asyncio.create_task(_run_deepthink_task(user_id=user_id, task_id=task_id, request=dict(req)))
        _track_background_runner(task_id, runner)
        return {"success": True}

    if task_type == "lesson_plan":
        await db_update_task_status(user_id=user_id, task_id=task_id, status="running", progress=0.0, error={})
        await db_append_task_event(
            user_id=user_id,
            task_id=task_id,
            event_type="step",
            payload={
                "step": {"id": "task_resumed", "title": "任务继续执行", "status": "running", "startTime": _now_iso()}
            },
        )
        _cancel_background_runner(task_id)
        runner = asyncio.create_task(_run_lesson_plan_task(user_id=user_id, task_id=task_id, request=dict(req)))
        _track_background_runner(task_id, runner)
        return {"success": True}

    raise HTTPException(status_code=400, detail="task_not_resumable")


@router.post("/{task_id}/cancel", response_model=dict)
async def cancel_task(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    ok = await compose_tasks.cancel_task(task_id=task_id, user_id=user_id)
    if ok:
        try:
            await db_update_task_status(
                user_id=user_id,
                task_id=task_id,
                status="canceled",
                error={"message": "Task cancelled"},
                ended_at=datetime.utcnow(),
            )
            await db_append_task_event(
                user_id=user_id,
                task_id=task_id,
                event_type="step",
                payload={
                    "step": {"id": "task_canceled", "title": "任务已取消", "status": "failed", "startTime": _now_iso()}
                },
            )
        except Exception:
            logger.exception("task_cancel_db_sync_failed", extra={"task_id": task_id, "user_id": user_id})
        return {"success": True}

    ok = await study_material_tasks.cancel_task(task_id=task_id, user_id=user_id)
    if ok:
        return {"success": True}

    db_task = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
    if not db_task:
        raise HTTPException(status_code=404, detail="task_not_found")

    await db_update_task_status(
        user_id=user_id,
        task_id=task_id,
        status="canceled",
        error={"message": "Task cancelled"},
        ended_at=datetime.utcnow(),
    )
    await db_append_task_event(
        user_id=user_id,
        task_id=task_id,
        event_type="step",
        payload={"step": {"id": "task_canceled", "title": "任务已取消", "status": "failed", "startTime": _now_iso()}},
    )
    _cancel_background_runner(task_id)
    return {"success": True}


@router.post("/{task_id}/retry", response_model=dict)
async def retry_task(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    db_task = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
    if not db_task:
        raise HTTPException(status_code=404, detail="task_not_found")

    task_type = str(db_task.get("task_type") or "").strip()
    req = db_task.get("request") if isinstance(db_task.get("request"), dict) else {}

    if task_type == "paper_compose":
        new_task_id = f"compose-{uuid.uuid4().hex[:12]}"
        new_req = dict(req)
        new_req["taskId"] = new_task_id

        async def runner_factory(task: PaperComposeTask):
            await _emit_db_task_started(
                user_id=user_id,
                task_id=task.task_id,
                task_type="paper_compose",
                title=str(
                    (task.request or {}).get("paperName") or (task.request or {}).get("paper_name") or "组卷任务"
                ),
                request=dict(task.request or {}),
            )
            try:
                async for evt in compose_paper_events(task.request, user_id=user_id):
                    if task.status != "running":
                        break
                    await compose_tasks.append_event(task, evt)
                    payload = {k: evt.get(k) for k in ("step", "progress", "result", "error", "message") if k in evt}
                    progress = None
                    if "progress" in payload:
                        try:
                            progress = float(payload.get("progress") or 0.0)
                        except Exception:
                            progress = None
                    await db_append_task_event(
                        user_id=user_id,
                        task_id=task.task_id,
                        event_type=str(evt.get("type") or "event"),
                        payload=payload,
                        seq=None,
                        progress=progress,
                    )
                    kind = str(evt.get("type") or "")
                    if kind == "result":
                        await compose_tasks.complete_task(task)
                        result = (
                            evt.get("result") if isinstance(evt.get("result"), dict) else {"result": evt.get("result")}
                        )
                        await _emit_db_task_terminal(
                            user_id=user_id, task_id=task.task_id, status="completed", result=result
                        )
                        return
                    if kind == "error":
                        await compose_tasks.fail_task(task, str(evt.get("error") or "compose_failed"))
                        await _emit_db_task_terminal(
                            user_id=user_id,
                            task_id=task.task_id,
                            status="failed",
                            error={"message": str(evt.get("error") or "compose_failed")},
                        )
                        return
            except asyncio.CancelledError:
                await compose_tasks.fail_task(task, "Task cancelled")
                await _emit_db_task_terminal(
                    user_id=user_id, task_id=task.task_id, status="canceled", error={"message": "Task cancelled"}
                )
                raise
            except Exception as exc:  # pragma: no cover
                await compose_tasks.fail_task(task, str(exc))
                await _emit_db_task_terminal(
                    user_id=user_id, task_id=task.task_id, status="failed", error={"message": str(exc)}
                )
            finally:
                if task.status == "running":
                    await compose_tasks.fail_task(task, "Task ended unexpectedly")
                    await _emit_db_task_terminal(
                        user_id=user_id,
                        task_id=task.task_id,
                        status="failed",
                        error={"message": "Task ended unexpectedly"},
                    )

        await compose_tasks.create_task(
            task_id=new_task_id, user_id=user_id, request=new_req, runner_factory=runner_factory
        )
        return {"success": True, "taskId": new_task_id}

    if task_type == "study_materials":
        query = str(req.get("query") or "").strip()
        subject = str(req.get("subject") or "").strip()
        options = req.get("options") if isinstance(req.get("options"), dict) else {}
        task = await study_material_tasks.create_task(
            query=query, user_id=user_id, subject=subject, options=dict(options)
        )
        return {"success": True, "taskId": task.task_id}

    if task_type == "deepthink":
        new_task_id = f"deepthink-{uuid.uuid4().hex[:12]}"
        title = f"深度解题：{str(req.get('subject') or '高中数学').strip() or '高中数学'}"
        await db_upsert_task(
            user_id=user_id,
            task_id=new_task_id,
            task_type="deepthink",
            title=title[:200],
            status="running",
            progress=0.0,
            request=dict(req),
            started_at=datetime.utcnow(),
        )
        await db_append_task_event(
            user_id=user_id,
            task_id=new_task_id,
            event_type="step",
            payload={
                "step": {
                    "id": "task_started",
                    "title": "开始深度解题",
                    "status": "running",
                    "startTime": _now_iso(),
                    "toolName": "deepthink",
                }
            },
        )
        runner = asyncio.create_task(_run_deepthink_task(user_id=user_id, task_id=new_task_id, request=dict(req)))
        _track_background_runner(new_task_id, runner)
        return {"success": True, "taskId": new_task_id}

    if task_type == "lesson_plan":
        new_task_id = f"lesson-plan-{uuid.uuid4().hex[:12]}"
        title = (
            f"教案：{str(req.get('subject') or '').strip()} {str(req.get('grade') or '').strip()}《{str(req.get('topic') or '').strip()}》"
        ).strip()
        await db_upsert_task(
            user_id=user_id,
            task_id=new_task_id,
            task_type="lesson_plan",
            title=title[:200] or "教案生成",
            status="running",
            progress=0.0,
            request=dict(req),
            started_at=datetime.utcnow(),
        )
        await db_append_task_event(
            user_id=user_id,
            task_id=new_task_id,
            event_type="step",
            payload={
                "step": {
                    "id": "task_started",
                    "title": "开始生成教案",
                    "status": "running",
                    "startTime": _now_iso(),
                    "toolName": "lesson_plan",
                }
            },
        )
        runner = asyncio.create_task(_run_lesson_plan_task(user_id=user_id, task_id=new_task_id, request=dict(req)))
        _track_background_runner(new_task_id, runner)
        return {"success": True, "taskId": new_task_id}

    if task_type == "export_paper":
        try:
            paper_id = int(req.get("paper_id") or req.get("paperId") or 0)
        except Exception:
            paper_id = 0
        new_task_id = f"export-paper-{uuid.uuid4().hex[:12]}"
        paper = await db_get_paper(user_id=user_id, paper_id=paper_id) if paper_id > 0 else None
        title = f"导出试卷：{str((paper or {}).get('paper_name') or (paper or {}).get('name') or paper_id)}"
        await _emit_db_task_started(
            user_id=user_id, task_id=new_task_id, task_type="export_paper", title=title[:200], request=dict(req)
        )
        runner = asyncio.create_task(_run_export_paper_task(user_id=user_id, task_id=new_task_id, request=dict(req)))
        _track_background_runner(new_task_id, runner)
        return {"success": True, "taskId": new_task_id}

    if task_type == "export_study_archive":
        try:
            archive_id = int(req.get("archive_id") or req.get("archiveId") or 0)
        except Exception:
            archive_id = 0
        new_task_id = f"export-archive-{uuid.uuid4().hex[:12]}"
        archive = await db_get_study_archive(user_id=user_id, archive_id=archive_id) if archive_id > 0 else None
        title = f"导出资料：{str((archive or {}).get('topic') or archive_id)}"
        await _emit_db_task_started(
            user_id=user_id,
            task_id=new_task_id,
            task_type="export_study_archive",
            title=title[:200],
            request=dict(req),
        )
        runner = asyncio.create_task(
            _run_export_study_archive_task(user_id=user_id, task_id=new_task_id, request=dict(req))
        )
        _track_background_runner(new_task_id, runner)
        return {"success": True, "taskId": new_task_id}

    raise HTTPException(status_code=400, detail="task_not_retryable")


@router.post("/export/papers/{paper_id}", response_model=dict)
async def export_paper_task(paper_id: int, payload: Optional[dict] = None, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    body = payload if isinstance(payload, dict) else {}
    fmt = str(body.get("format") or body.get("fmt") or "markdown").strip().lower()
    req = {
        "paper_id": int(paper_id),
        "format": fmt,
        "include_stem": bool(body.get("includeStem")) if "includeStem" in body else bool(body.get("include_stem")),
        "include_answer": bool(body.get("includeAnswer"))
        if "includeAnswer" in body
        else bool(body.get("include_answer")),
        "include_analysis": bool(body.get("includeAnalysis"))
        if "includeAnalysis" in body
        else bool(body.get("include_analysis")),
    }

    task_id = f"export-paper-{uuid.uuid4().hex[:12]}"
    paper = await db_get_paper(user_id=user_id, paper_id=int(paper_id))
    title = f"导出试卷：{str((paper or {}).get('paper_name') or (paper or {}).get('name') or paper_id)}"
    await _emit_db_task_started(
        user_id=user_id, task_id=task_id, task_type="export_paper", title=title[:200], request=req
    )
    runner = asyncio.create_task(_run_export_paper_task(user_id=user_id, task_id=task_id, request=req))
    _track_background_runner(task_id, runner)
    return {"success": True, "taskId": task_id}


@router.post("/export/study-archives/{archive_id}", response_model=dict)
async def export_study_archive_task(
    archive_id: int, payload: Optional[dict] = None, user: dict = Depends(require_auth)
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    body = payload if isinstance(payload, dict) else {}
    fmt = str(body.get("format") or body.get("fmt") or "markdown").strip().lower()
    req = {"archive_id": int(archive_id), "format": fmt}

    task_id = f"export-archive-{uuid.uuid4().hex[:12]}"
    archive = await db_get_study_archive(user_id=user_id, archive_id=int(archive_id))
    title = f"导出资料：{str((archive or {}).get('topic') or archive_id)}"
    await _emit_db_task_started(
        user_id=user_id, task_id=task_id, task_type="export_study_archive", title=title[:200], request=req
    )
    runner = asyncio.create_task(_run_export_study_archive_task(user_id=user_id, task_id=task_id, request=req))
    _track_background_runner(task_id, runner)
    return {"success": True, "taskId": task_id}


@router.get("/{task_id}/stream")
async def stream_task(
    task_id: str,
    after_seq: int = Query(0),
    user: dict = Depends(require_auth),
) -> StreamingResponse:
    heartbeat_s = float(os.getenv("PAPER_COMPOSE_SSE_HEARTBEAT_S") or "4.0")
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    async def event_generator():
        compose_task = await compose_tasks.get_task(task_id)
        if compose_task and str(compose_task.user_id or "") == user_id:
            async for event in compose_tasks.stream(task_id, after_seq=after_seq, heartbeat_s=heartbeat_s):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            return

        # DB-backed replay/poll stream (best-effort).
        last_sent = max(0, int(after_seq or 0))
        last_ping_at = 0.0
        while True:
            task = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
            if not task:
                yield f"data: {json.dumps({'taskId': task_id, 'seq': last_sent, 'type': 'error', 'data': {'error': 'task_not_found'}}, ensure_ascii=False)}\n\n"
                return

            events = await db_list_task_events(user_id=user_id, task_id=task_id, after_seq=last_sent, limit=500)
            for evt in events:
                seq = int(evt.get("seq") or 0)
                if seq <= last_sent:
                    continue
                last_sent = seq
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

            if str(task.get("status") or "") != "running":
                return

            now = time.time()
            if now - last_ping_at >= max(1.0, float(heartbeat_s or 4.0)):
                last_ping_at = now
                yield f"data: {json.dumps({'taskId': task_id, 'seq': last_sent, 'type': 'ping', 'data': {'status': 'running', 'last_seq': last_sent}}, ensure_ascii=False)}\n\n"

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )
