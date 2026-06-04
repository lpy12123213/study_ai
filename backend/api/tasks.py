from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.knowledge_video_schemas import KnowledgeVideoGenerateRequest
from backend.api.lesson_plan_schemas import LessonPlanGenerateRequest
from backend.api.question_evaluate_schemas import QuestionEvaluateRequest
from backend.api.question_library_schemas import (
    QuestionLibraryCrawlRequest,
    QuestionLibraryGenerateRequest,
    QuestionLibraryScoreRequest,
)
from backend.api.schemas import DeepThinkRequest
from backend.api.sse_polling import next_poll_delay, wait_for_task_event_or_timeout
from backend.api.sse_utils import is_sse_client_disconnected
from backend.api.study_materials_schemas import StudyMaterialsContinueRequest, StudyMaterialsGenerateRequest
from backend.core.logging_utils import get_logger
from backend.core.text_utils import clip_text as _clip_text
from backend.core.time_utils import utcnow_naive
from backend.database.repositories.system.tasks import (
    append_task_event as db_append_task_event,
)
from backend.database.repositories.system.tasks import (
    average_duration_seconds as db_average_duration_seconds,
)
from backend.database.repositories.system.tasks import (
    get_task as db_get_task,
)
from backend.database.repositories.system.tasks import (
    list_task_events as db_list_task_events,
)
from backend.database.repositories.system.tasks import (
    list_tasks as db_list_tasks,
)
from backend.database.repositories.system.tasks import (
    update_task_status as db_update_task_status,
)
from backend.generation.essay_evaluation.essay_schemas import EssayEvaluationRequest
from backend.shared.tasks import task_runtime
from backend.tasks import (
    submit_deepthink_task,
    submit_essay_evaluation_task,
    submit_export_paper_task,
    submit_export_study_archive_task,
    submit_generate_full_paper_task,
    submit_knowledge_video_task,
    submit_lesson_plan_task,
    submit_paper_compose_task,
    submit_question_evaluate_task,
)

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
        except ValueError:
            started_ts = None
        if not started_ts:
            continue

        elapsed_s = max(0.0, now - started_ts)
        avg_s = averages.get(ttype)
        if avg_s and avg_s > 1:
            t["elapsed_s"] = elapsed_s
            t["eta_s"] = max(0.0, float(avg_s) - elapsed_s)

    return {"tasks": items, "count": len(items)}


@router.post("/deepthink", response_model=dict)
async def submit_deepthink(request: DeepThinkRequest, user: dict = Depends(require_auth)) -> dict:
    """Canonical long-task submit endpoint for DeepThink."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    task = await submit_deepthink_task(user_id=user_id, request=request.model_dump())
    return {"success": True, "taskId": task.task_id}


@router.post("/lesson-plans/generate", response_model=dict)
async def submit_lesson_plan(request: LessonPlanGenerateRequest, user: dict = Depends(require_auth)) -> dict:
    """Canonical long-task submit endpoint for lesson-plan generation."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    task = await submit_lesson_plan_task(user_id=user_id, request=request.model_dump())
    return {"success": True, "taskId": task.task_id}


@router.post("/papers/compose", response_model=dict)
async def submit_paper_compose(payload: dict, user: dict = Depends(require_auth)) -> dict:
    """Canonical long-task submit endpoint for paper composing."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_payload")

    task = await submit_paper_compose_task(user_id=user_id, request=payload)
    return {"success": True, "taskId": task.task_id}


@router.post("/papers/generate-full", response_model=dict)
async def submit_generate_full_paper(payload: Optional[dict] = None, user: dict = Depends(require_auth)) -> dict:
    """Canonical long-task submit endpoint for one-click full paper generation."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    body = payload if isinstance(payload, dict) else {}
    task = await submit_generate_full_paper_task(user_id=user_id, request=body)
    return {"success": True, "taskId": task.task_id}


@router.post("/knowledge-videos/generate", response_model=dict)
async def submit_knowledge_video(request: KnowledgeVideoGenerateRequest, user: dict = Depends(require_auth)) -> dict:
    """Canonical long-task submit endpoint for AI-generated Manim knowledge videos."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    task = await submit_knowledge_video_task(user_id=user_id, request=request.model_dump())
    return {"success": True, "taskId": task.task_id}


@router.post("/study-materials/generate", response_model=dict)
async def submit_study_materials(request: StudyMaterialsGenerateRequest, user: dict = Depends(require_auth)) -> dict:
    """Canonical long-task submit endpoint for study-materials generation."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    query = (request.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty query")

    subject = (request.subject or "").strip()
    options = {}
    if (request.preset or "").strip():
        options["preset"] = str(request.preset or "").strip()
    if (request.requirements or "").strip():
        options["requirements"] = _clip_text(str(request.requirements or "").strip(), max_chars=600)
    if request.with_questions is not None:
        options["with_questions"] = bool(request.with_questions)
    if request.with_diagrams is not None:
        options["with_diagrams"] = bool(request.with_diagrams)
    if request.enable_extra_tools is not None:
        options["enable_extra_tools"] = bool(request.enable_extra_tools)
    if request.max_points is not None:
        try:
            n = int(request.max_points)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            options["max_points"] = max(1, min(n, 15))
    if request.prefer_local_archive is not None:
        options["preferLocalArchive"] = bool(request.prefer_local_archive)

    from backend.generation.study_materials.orchestrator_singleton import study_material_tasks

    task = await study_material_tasks.create_task(query=query, user_id=user_id, subject=subject, options=options)
    return {"success": True, "taskId": task.task_id}


@router.post("/study-materials/{task_id}/continue", response_model=dict)
async def continue_study_materials_task(
    task_id: str,
    request: StudyMaterialsContinueRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Create a follow-up study-materials task (one bounded continuation iteration)."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    mode = str(request.mode or "").strip() or "improve"

    from backend.generation.study_materials.orchestrator_singleton import study_material_tasks

    try:
        new_task = await study_material_tasks.continue_task(task_id=task_id, user_id=user_id, mode=mode)
    except ValueError as exc:
        msg = str(exc)
        if msg == "task_not_found":
            raise HTTPException(status_code=404, detail="Task not found")
        if msg == "task_running":
            raise HTTPException(status_code=409, detail="Task still running")
        if msg == "task_not_resumable":
            raise HTTPException(status_code=400, detail="Task not resumable")
        raise HTTPException(status_code=400, detail=msg)

    return {"success": True, "taskId": new_task.task_id}


@router.post("/question-library/crawl", response_model=dict)
async def submit_question_library_crawl(request: QuestionLibraryCrawlRequest, user: dict = Depends(require_auth)) -> dict:
    """Canonical long-task submit endpoint for question-library crawling."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    from backend.generation.question_library import runner as ql_runner
    from backend.generation.question_library.runner import RunnerError

    try:
        task = await ql_runner.create_crawl_task(user_id=user_id, request=request.model_dump())
    except RunnerError as exc:
        raise HTTPException(status_code=int(exc.status_code), detail=str(exc.detail)) from exc
    return {"success": True, "taskId": task.task_id}


@router.post("/question-library/generate", response_model=dict)
async def submit_question_library_generate(
    request: QuestionLibraryGenerateRequest, user: dict = Depends(require_auth)
) -> dict:
    """Canonical long-task submit endpoint for question-library generation."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    from backend.generation.question_library import runner as ql_runner
    from backend.generation.question_library.runner import RunnerError

    try:
        task = await ql_runner.create_generate_task(user_id=user_id, request=request.model_dump())
    except RunnerError as exc:
        raise HTTPException(status_code=int(exc.status_code), detail=str(exc.detail)) from exc
    return {"success": True, "taskId": task.task_id}


@router.post("/question-library/import-media", response_model=dict)
async def submit_question_library_import_media(
    subject: str = Form(""),
    topic: str = Form(""),
    difficulty: str = Form(""),
    question_type: str = Form(""),
    count: int = Form(10),
    max_pdf_pages: int = Form(12),
    task_id: str = Form(""),
    files: list[UploadFile] = File(...),
    user: dict = Depends(require_auth),
) -> dict:
    """Canonical long-task submit endpoint for question-library image/PDF import."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    from backend.generation.question_library import runner as ql_runner
    from backend.generation.question_library.media_import import (
        MediaImportError,
        persist_upload_files,
        safe_media_import_task_id,
    )
    from backend.generation.question_library.runner import RunnerError

    tid = safe_media_import_task_id(task_id)
    try:
        refs = await persist_upload_files(task_id=tid, uploads=files or [])
        task = await ql_runner.create_media_import_task(
            user_id=user_id,
            request={
                "task_id": tid,
                "subject": subject,
                "topic": topic,
                "difficulty": difficulty,
                "question_type": question_type,
                "count": count,
                "max_pdf_pages": max_pdf_pages,
                "files": [
                    {
                        "path": str(ref.path),
                        "filename": ref.filename,
                        "content_type": ref.content_type,
                    }
                    for ref in refs
                ],
            },
        )
    except MediaImportError as exc:
        detail = str(exc) or "media_import_error"
        if detail == "file_too_large":
            raise HTTPException(status_code=413, detail=detail) from exc
        if detail == "unsupported_media_type":
            raise HTTPException(status_code=415, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    except RunnerError as exc:
        raise HTTPException(status_code=int(exc.status_code), detail=str(exc.detail)) from exc
    return {"success": True, "taskId": task.task_id}


@router.post("/question-library/score", response_model=dict)
async def submit_question_library_score(request: QuestionLibraryScoreRequest, user: dict = Depends(require_auth)) -> dict:
    """Canonical long-task submit endpoint for question-library scoring."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    from backend.generation.question_library import runner as ql_runner
    from backend.generation.question_library.runner import RunnerError

    try:
        task = await ql_runner.create_score_task(user_id=user_id, request=request.model_dump())
    except RunnerError as exc:
        raise HTTPException(status_code=int(exc.status_code), detail=str(exc.detail)) from exc
    return {"success": True, "taskId": task.task_id}


@router.post("/question-evaluate/evaluate", response_model=dict)
async def submit_question_evaluate(request: QuestionEvaluateRequest, user: dict = Depends(require_auth)) -> dict:
    """Canonical long-task submit endpoint for question quality evaluation."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    task = await submit_question_evaluate_task(user_id=user_id, request=request.model_dump())
    return {"success": True, "taskId": task.task_id}


@router.post("/essay-evaluations/evaluate", response_model=dict)
async def submit_essay_evaluation(request: EssayEvaluationRequest, user: dict = Depends(require_auth)) -> dict:
    """Canonical long-task submit endpoint for essay evaluation.

    The runner persists the result to ``essay_evaluations`` and emits SSE
    progress + a final ``done`` event with the structured rubric output.
    """

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    task = await submit_essay_evaluation_task(user_id=user_id, request=request.model_dump())
    return {"success": True, "taskId": task.task_id}


@router.get("/{task_id}", response_model=dict)
async def get_task_status(
    task_id: str,
    include_events: bool = Query(False),
    events_limit: int = Query(200, ge=1, le=5000),
    events_after_seq: int = Query(0, ge=0),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    db_task = await db_get_task(
        user_id=user_id,
        task_id=task_id,
        include_events=include_events,
        events_limit=events_limit,
        events_after_seq=events_after_seq,
    )
    if not db_task:
        # Back-compat: in-memory runtime status payload.
        payload = await task_runtime.status_payload(
            task_id=task_id,
            user_id=user_id,
            include_events=include_events,
            events_limit=events_limit,
        )
        if payload:
            return payload
        raise HTTPException(status_code=404, detail="task_not_found")

    if str(db_task.get("status") or "") == "running":
        ttype = str(db_task.get("task_type") or "").strip()
        started_at = str(db_task.get("started_at") or "").strip()
        try:
            started_ts = datetime.fromisoformat(started_at.replace("Z", "+00:00")).timestamp() if started_at else None
        except ValueError:
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
                logger.warning(
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
    ok = await task_runtime.pause_task(task_id=task_id, user_id=user_id)
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
    return {"success": True}


@router.post("/{task_id}/resume", response_model=dict)
async def resume_task(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await task_runtime.resume_task(task_id=task_id, user_id=user_id)
    if ok:
        return {"success": True}

    db_task = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
    if not db_task:
        raise HTTPException(status_code=404, detail="task_not_found")

    status = str(db_task.get("status") or "").strip()
    if status == "running":
        return {"success": True}
    if status != "paused":
        raise HTTPException(status_code=400, detail="task_not_resumable")

    raise HTTPException(status_code=400, detail="task_not_resumable")


@router.post("/{task_id}/cancel", response_model=dict)
async def cancel_task(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    ok = await task_runtime.cancel_task(task_id=task_id, user_id=user_id)
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
        ended_at=utcnow_naive(),
    )
    await db_append_task_event(
        user_id=user_id,
        task_id=task_id,
        event_type="step",
        payload={"step": {"id": "task_canceled", "title": "任务已取消", "status": "failed", "startTime": _now_iso()}},
    )
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
        task = await submit_paper_compose_task(user_id=user_id, request=new_req, parent_task_id=task_id)
        return {"success": True, "taskId": task.task_id}

    if task_type == "study_materials":
        query = str(req.get("query") or "").strip()
        subject = str(req.get("subject") or "").strip()
        options = req.get("options") if isinstance(req.get("options"), dict) else {}
        from backend.generation.study_materials.orchestrator_singleton import study_material_tasks

        task = await study_material_tasks.create_task(
            query=query,
            user_id=user_id,
            subject=subject,
            options=dict(options),
            parent_task_id=task_id,
        )
        return {"success": True, "taskId": task.task_id}

    if task_type == "deepthink":
        task = await submit_deepthink_task(user_id=user_id, request=dict(req), parent_task_id=task_id)
        return {"success": True, "taskId": task.task_id}

    if task_type == "lesson_plan":
        task = await submit_lesson_plan_task(user_id=user_id, request=dict(req), parent_task_id=task_id)
        return {"success": True, "taskId": task.task_id}

    if task_type == "export_paper":
        task = await submit_export_paper_task(user_id=user_id, request=dict(req), parent_task_id=task_id)
        return {"success": True, "taskId": task.task_id}

    if task_type == "export_study_archive":
        task = await submit_export_study_archive_task(user_id=user_id, request=dict(req), parent_task_id=task_id)
        return {"success": True, "taskId": task.task_id}

    if task_type == "knowledge_video":
        task = await submit_knowledge_video_task(user_id=user_id, request=dict(req), parent_task_id=task_id)
        return {"success": True, "taskId": task.task_id}

    if task_type == "question_evaluate":
        task = await submit_question_evaluate_task(user_id=user_id, request=dict(req), parent_task_id=task_id)
        return {"success": True, "taskId": task.task_id}

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

    task = await submit_export_paper_task(user_id=user_id, request=req)
    return {"success": True, "taskId": task.task_id}


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

    task = await submit_export_study_archive_task(user_id=user_id, request=req)
    return {"success": True, "taskId": task.task_id}


@router.get("/{task_id}/stream")
async def stream_task(
    task_id: str,
    request: Request,
    after_seq: int = Query(0),
    user: dict = Depends(require_auth),
) -> StreamingResponse:
    heartbeat_s = float(os.getenv("PAPER_COMPOSE_SSE_HEARTBEAT_S") or "4.0")
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    async def event_generator():
        # Durable replay/poll stream. The tasks table is the source of truth so a
        # refreshed browser can replay progress even while the in-memory runner is
        # still alive and its bounded event buffer has moved on.
        last_sent = max(0, int(after_seq or 0))
        last_ping_at = 0.0
        poll_delay = 0.1
        while True:
            task = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
            if not task:
                runtime_task = await task_runtime.get_task(task_id)
                if runtime_task and str(runtime_task.user_id or "") == user_id:
                    async for event in task_runtime.stream(task_id, after_seq=last_sent, heartbeat_s=heartbeat_s):
                        if await is_sse_client_disconnected(request):
                            return
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    return
                if await is_sse_client_disconnected(request):
                    return
                yield f"data: {json.dumps({'taskId': task_id, 'seq': last_sent, 'type': 'error', 'data': {'error': 'task_not_found'}}, ensure_ascii=False)}\n\n"
                return

            events = await db_list_task_events(user_id=user_id, task_id=task_id, after_seq=last_sent, limit=500)
            had_events = False
            for evt in events:
                seq = int(evt.get("seq") or 0)
                if seq <= last_sent:
                    continue
                last_sent = seq
                had_events = True
                if await is_sse_client_disconnected(request):
                    return
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

            if len(events) >= 500:
                poll_delay = next_poll_delay(poll_delay, had_events=True)
                continue

            if str(task.get("status") or "") != "running":
                return

            now = time.time()
            if now - last_ping_at >= max(1.0, float(heartbeat_s or 4.0)):
                last_ping_at = now
                if await is_sse_client_disconnected(request):
                    return
                yield f"data: {json.dumps({'taskId': task_id, 'seq': last_sent, 'type': 'ping', 'data': {'status': 'running', 'last_seq': last_sent}}, ensure_ascii=False)}\n\n"

            if await is_sse_client_disconnected(request):
                return
            poll_delay = next_poll_delay(poll_delay, had_events=had_events)
            await wait_for_task_event_or_timeout(
                runtime=task_runtime,
                task_id=task_id,
                user_id=user_id,
                last_seq=last_sent,
                timeout_s=poll_delay,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )
