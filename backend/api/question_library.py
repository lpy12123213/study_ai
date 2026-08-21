from __future__ import annotations

import json
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.question_library_schemas import (
    GaokaoQuestionCrawlRequest,
    GaokaoQuestionImportRequest,
    QuestionLibraryBulkDeleteRequest,
    QuestionLibraryCommitPreviewRequest,
    QuestionLibraryCommitPreviewResponse,
    QuestionLibraryCrawlRequest,
    QuestionLibraryGenerateRequest,
    QuestionLibraryLatestPendingPreviewResponse,
    QuestionLibraryPracticeStatePatch,
    QuestionLibraryPreviewResponse,
    QuestionLibraryRegenerateSectionRequest,
    QuestionLibraryScoreRequest,
)
from backend.api.sse_polling import next_poll_delay, wait_for_task_event_or_timeout
from backend.api.sse_utils import is_sse_client_disconnected
from backend.core.audit import AuditAction, audit_logger
from backend.database.repositories.question.gaokao import upsert_gaokao_questions
from backend.database.repositories.question.question_cache import get_question_cache
from backend.database.repositories.question.question_library import (
    bulk_delete_question_library_items,
    get_question_library_item,
    list_question_library_items,
    set_hidden,
    set_starred,
)
from backend.database.repositories.system.tasks import get_task as db_get_task
from backend.database.repositories.system.tasks import list_task_events as db_list_task_events
from backend.generation.question_library import runner as ql_runner
from backend.generation.question_library import session_service
from backend.generation.question_library.preview_store import load_preview
from backend.generation.question_library.runner import RunnerError
from backend.generation.question_library.session_utils import serialize_session_preview
from backend.integrations.crawler.manager import get_crawler
from backend.shared.tasks import task_runtime

router = APIRouter(prefix="/question-library", tags=["question-library"], dependencies=[Depends(require_auth)])


def _require_user_id(user: dict) -> str:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return user_id


def _sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


async def _stream_task(task_id: str, *, after_seq: int, request: Request | None = None) -> StreamingResponse:
    heartbeat_s = float(os.getenv("QUESTION_LIBRARY_SSE_HEARTBEAT_S") or "4.0")

    async def event_generator():
        async for event in task_runtime.stream(task_id, after_seq=after_seq, heartbeat_s=heartbeat_s):
            if request is not None and await is_sse_client_disconnected(request):
                return
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


async def _stream_task_from_db(
    *, task_id: str, user_id: str, after_seq: int, request: Request | None = None
) -> StreamingResponse:
    """DB-backed SSE stream for question-library tasks (survives process restart)."""

    heartbeat_s = float(os.getenv("QUESTION_LIBRARY_SSE_HEARTBEAT_S") or "4.0")

    async def event_generator():
        last_sent = max(0, int(after_seq or 0))
        last_ping_at = 0.0
        poll_delay = 0.1
        while True:
            if request is not None and await is_sse_client_disconnected(request):
                return
            task = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
            if not task:
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
                if request is not None and await is_sse_client_disconnected(request):
                    return
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

            if str(task.get("status") or "") != "running":
                return

            now = time.time()
            if now - last_ping_at >= max(1.0, float(heartbeat_s or 4.0)):
                last_ping_at = now
                yield f"data: {json.dumps({'taskId': task_id, 'seq': last_sent, 'type': 'ping', 'data': {'status': 'running', 'last_seq': last_sent}}, ensure_ascii=False)}\n\n"

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

@router.get("/items", response_model=dict)
async def list_items(
    subject: str = Query(""),
    origin: str = Query(""),
    area: str = Query("general"),
    hidden: str = Query("0"),
    q: str = Query(""),
    exam_scene: str = Query(""),
    question_type: str = Query(""),
    difficulty: str = Query(""),
    category: str = Query(""),
    year: str = Query(""),
    region: str = Query(""),
    grade: str = Query(""),
    semester: str = Query(""),
    method: str = Query(""),
    only_new: bool = Query(False),
    min_score: Optional[int] = Query(None),
    sort: str = Query("updated_at"),
    order: str = Query("desc"),
    limit: int = Query(50),
    offset: int = Query(0),
    include_total: bool = Query(True),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = _require_user_id(user)
    return await list_question_library_items(
        user_id=user_id,
        subject=subject,
        origin=origin,
        area=area if area in {"general", "gaokao", "all"} else "general",
        hidden=hidden if hidden in {"0", "1", "all"} else "0",
        q=q,
        exam_scene=exam_scene,
        question_type=question_type,
        difficulty=difficulty,
        category=category,
        year=year,
        region=region,
        grade=grade,
        semester=semester,
        method=method,
        only_new=only_new,
        min_score=min_score,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
        include_total=include_total,
    )


@router.post("/gaokao/items/import", response_model=dict, include_in_schema=False)
@router.post("/gaokao/items/manual-import", response_model=dict)
async def manual_import_gaokao_items(
    request: GaokaoQuestionImportRequest, user: dict = Depends(require_auth)
) -> dict:
    user_id = _require_user_id(user)
    try:
        result = await upsert_gaokao_questions(
            user_id=user_id,
            items=[item.model_dump() for item in request.items],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, **result}


@router.get("/items/{question_id}", response_model=dict)
async def get_item_detail(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    item = await get_question_library_item(user_id=user_id, question_id=question_id)
    if not item:
        raise HTTPException(status_code=404, detail="not_found")

    cache = await get_question_cache(question_ids=[str(question_id or "").strip()])
    return {"library_item": item, "question_cache": cache.get(str(question_id or "").strip())}


@router.post("/items/{question_id}/hide", response_model=dict)
async def hide_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    ok = await set_hidden(user_id=user_id, question_id=question_id, hidden=True)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/unhide", response_model=dict)
async def unhide_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    ok = await set_hidden(user_id=user_id, question_id=question_id, hidden=False)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/star", response_model=dict)
async def star_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    ok = await set_starred(user_id=user_id, question_id=question_id, starred=True)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/unstar", response_model=dict)
async def unstar_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    ok = await set_starred(user_id=user_id, question_id=question_id, starred=False)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/bulk-delete", response_model=dict)
async def bulk_delete_items(request: QuestionLibraryBulkDeleteRequest, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    question_ids = [str(qid or "").strip() for qid in (request.question_ids or []) if str(qid or "").strip()]
    if not question_ids:
        return {"success": True, "deleted": 0}
    deleted = await bulk_delete_question_library_items(user_id=user_id, question_ids=question_ids)
    audit_logger.log(
        user_id=user_id,
        action=AuditAction.QUESTION_LIBRARY_BULK_DELETE,
        resource="/api/question-library/items/bulk-delete",
        details={"requested": len(question_ids), "deleted": int(deleted or 0)},
    )
    return {"success": True, "deleted": int(deleted or 0)}


@router.post("/items/{question_id}/export-to-basket", response_model=dict)
async def export_item_to_basket(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    qid = str(question_id or "").strip()
    if not qid:
        raise HTTPException(status_code=400, detail="missing_question_id")

    item = await get_question_library_item(user_id=user_id, question_id=qid)
    if not item:
        raise HTTPException(status_code=404, detail="not_found")

    cache = await get_question_cache(question_ids=[qid])
    cached = cache.get(qid) if isinstance(cache, dict) else None
    subject = str((item or {}).get("subject") or (cached or {}).get("subject") or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="subject_required")

    detail = {
        "question_id": qid,
        "type": str((cached or {}).get("question_type") or "").strip() or "解答题",
        "difficulty": str((cached or {}).get("difficulty") or "").strip() or "中等",
        "source": str((cached or {}).get("source") or "").strip() or "本地题库",
        "knowledge_points": str((item or {}).get("knowledge_point") or "").strip(),
    }

    crawler = await get_crawler(subject=subject, edu_level="", strict=True)
    try:
        result = await crawler.export_to_basket(
            [qid], question_details=[detail], auto_login=True, auto_switch_subject=True
        )
    except Exception:
        raise HTTPException(status_code=500, detail="export_failed")
    return result if isinstance(result, dict) else {"success": False, "error": "export_failed"}


@router.get("/tasks/{task_id}", response_model=dict)
async def get_task_status(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    payload = await task_runtime.status_payload(task_id=task_id, user_id=user_id)
    if payload:
        return {
            "taskId": str(payload.get("taskId") or task_id).strip() or task_id,
            "kind": str(payload.get("type") or "").strip(),
            "status": str(payload.get("status") or "").strip(),
            "progress": float(payload.get("progress") or 0.0),
            "steps": payload.get("steps") if isinstance(payload.get("steps"), list) else [],
            "error": payload.get("error"),
            "first_seq": int(payload.get("first_seq") or 1),
            "last_seq": int(payload.get("last_seq") or 0),
        }

    task = await db_get_task(user_id=user_id, task_id=task_id, include_events=True, events_limit=500)
    if not task:
        raise HTTPException(status_code=404, detail="task_not_found")

    events = task.get("events") if isinstance(task.get("events"), list) else []
    steps_by_id: dict[str, dict] = {}
    error_msg = ""
    for evt in events:
        if not isinstance(evt, dict):
            continue
        data = evt.get("data") if isinstance(evt.get("data"), dict) else {}
        step = data.get("step") if isinstance(data.get("step"), dict) else None
        if step:
            sid = str(step.get("id") or "").strip()
            if sid:
                steps_by_id[sid] = step
        if (not error_msg) and str(evt.get("type") or "") == "error":
            error_msg = str(data.get("error") or data.get("message") or "").strip()
        if (not error_msg) and str(evt.get("type") or "") in {"warning", "warn"}:
            error_msg = str(data.get("message") or "").strip()

    steps = list(steps_by_id.values())
    steps.sort(key=lambda s: str(s.get("startTime") or ""))
    if not error_msg:
        err_obj = task.get("error") if isinstance(task, dict) else None
        if isinstance(err_obj, dict):
            error_msg = str(err_obj.get("message") or err_obj.get("error") or "").strip()
    return {
        "taskId": str(task.get("id") or task_id).strip() or task_id,
        "kind": str(task.get("task_type") or "").strip(),
        "status": str(task.get("status") or "").strip(),
        "progress": float(task.get("progress") or 0.0),
        "steps": steps,
        "error": error_msg or None,
        "first_seq": 1,
        "last_seq": int(task.get("last_seq") or 0),
    }


@router.get("/tasks/{task_id}/stream")
async def stream_task(
    task_id: str,
    request: Request,
    after_seq: int = Query(0, ge=0),
    user: dict = Depends(require_auth),
) -> StreamingResponse:
    user_id = _require_user_id(user)
    task = await task_runtime.get_task(task_id)
    if task and task.user_id == user_id:
        return await _stream_task(task.task_id, after_seq=after_seq, request=request)

    # Restart-safe fallback: replay/poll events from DB.
    return await _stream_task_from_db(
        task_id=str(task_id or "").strip(), user_id=user_id, after_seq=after_seq, request=request
    )


@router.get("/previews/{preview_id}", response_model=QuestionLibraryPreviewResponse)
async def get_preview(preview_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")

    obj = load_preview(pid)
    if not obj or str(obj.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="preview_not_found")
    return {"success": True, **serialize_session_preview(obj)}


@router.get("/previews/latest/pending", response_model=QuestionLibraryLatestPendingPreviewResponse)
async def get_latest_pending_preview(user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    return session_service.get_latest_pending_preview(user_id=user_id)


@router.get("/sessions", response_model=dict)
async def list_question_library_sessions(user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    return await session_service.list_question_library_sessions(user_id=user_id)


@router.get("/sessions/{session_id}", response_model=dict)
async def get_question_library_session(session_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    return await session_service.get_question_library_session(user_id=user_id, session_id=session_id)


@router.post("/sessions/{session_id}/stop", response_model=dict)
async def stop_question_library_session(session_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    return await session_service.stop_question_library_session(user_id=user_id, session_id=session_id)


@router.post("/sessions/{session_id}/archive", response_model=dict)
async def archive_question_library_session(session_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    return await session_service.archive_question_library_session(user_id=user_id, session_id=session_id)


@router.post("/previews/{preview_id}/commit", response_model=QuestionLibraryCommitPreviewResponse)
async def commit_preview(
    preview_id: str, request: QuestionLibraryCommitPreviewRequest, user: dict = Depends(require_auth)
) -> dict:
    user_id = _require_user_id(user)
    questions = [q.model_dump() for q in (request.questions or [])]
    out = await session_service.commit_preview_to_library(user_id=user_id, preview_id=preview_id, questions=questions)
    audit_logger.log(
        user_id=user_id,
        action=AuditAction.QUESTION_LIBRARY_COMMIT,
        resource=f"/api/question-library/previews/{str(preview_id or '').strip()}/commit",
        details={"confirmed": len(questions)},
    )
    return out


@router.post("/previews/{preview_id}/discard", response_model=dict)
async def discard_preview(preview_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    out = await session_service.discard_preview(user_id=user_id, preview_id=preview_id)
    audit_logger.log(
        user_id=user_id,
        action=AuditAction.QUESTION_LIBRARY_DISCARD,
        resource=f"/api/question-library/previews/{str(preview_id or '').strip()}/discard",
        details={},
    )
    return out


@router.post("/sessions/{session_id}/questions/{question_id}/review", response_model=dict)
async def review_session_question(session_id: str, question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    return await session_service.review_session_question(user_id=user_id, session_id=session_id, question_id=question_id)


@router.patch("/sessions/{session_id}/questions/{question_id}/practice-state", response_model=dict)
async def update_session_question_practice_state(
    session_id: str,
    question_id: str,
    request: QuestionLibraryPracticeStatePatch,
    user: dict = Depends(require_auth),
) -> dict:
    user_id = _require_user_id(user)
    return await session_service.update_session_question_practice_state(
        user_id=user_id,
        session_id=session_id,
        question_id=question_id,
        patch=request.model_dump(exclude_unset=True),
    )


@router.post("/sessions/{session_id}/questions/{question_id}/approve", response_model=dict)
async def approve_session_question(session_id: str, question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    return await session_service.approve_session_question(user_id=user_id, session_id=session_id, question_id=question_id)


@router.post("/sessions/{session_id}/questions/{question_id}/reject", response_model=dict)
async def reject_session_question(session_id: str, question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    return await session_service.reject_session_question(user_id=user_id, session_id=session_id, question_id=question_id)


@router.post("/sessions/{session_id}/questions/{question_id}/confirm", response_model=dict)
async def confirm_session_question(session_id: str, question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    return await session_service.confirm_session_question(user_id=user_id, session_id=session_id, question_id=question_id)


@router.post("/sessions/{session_id}/questions/{question_id}/unconfirm", response_model=dict)
async def unconfirm_session_question(session_id: str, question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = _require_user_id(user)
    return await session_service.unconfirm_session_question(user_id=user_id, session_id=session_id, question_id=question_id)


@router.post("/previews/{preview_id}/regenerate-section")
async def regenerate_preview_section(
    preview_id: str, request: QuestionLibraryRegenerateSectionRequest, user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = _require_user_id(user)
    return await session_service.regenerate_preview_section(
        user_id=user_id,
        preview_id=preview_id,
        question_id=str(request.question_id or "").strip(),
        section_key=str(request.section_key or "").strip(),
    )


@router.post("/crawl")
async def crawl_and_save(
    request: QuestionLibraryCrawlRequest, http_request: Request, user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = _require_user_id(user)
    try:
        task = await ql_runner.create_crawl_task(user_id=user_id, request=request.model_dump())
    except RunnerError as exc:
        raise HTTPException(status_code=int(exc.status_code), detail=str(exc.detail)) from exc
    return await _stream_task(task.task_id, after_seq=0, request=http_request)


@router.post("/gaokao/crawl")
async def crawl_gaokao_and_save(
    request: GaokaoQuestionCrawlRequest, http_request: Request, user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = _require_user_id(user)
    try:
        task = await ql_runner.create_gaokao_crawl_task(user_id=user_id, request=request.model_dump())
    except RunnerError as exc:
        raise HTTPException(status_code=int(exc.status_code), detail=str(exc.detail)) from exc
    return await _stream_task(task.task_id, after_seq=0, request=http_request)


@router.post("/generate")
async def generate_and_save(
    request: QuestionLibraryGenerateRequest, http_request: Request, user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = _require_user_id(user)
    try:
        task = await ql_runner.create_generate_task(user_id=user_id, request=request.model_dump())
    except RunnerError as exc:
        raise HTTPException(status_code=int(exc.status_code), detail=str(exc.detail)) from exc
    return await _stream_task(task.task_id, after_seq=0, request=http_request)


@router.post("/score")
async def score_question_library(
    request: QuestionLibraryScoreRequest, http_request: Request, user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = _require_user_id(user)
    try:
        task = await ql_runner.create_score_task(user_id=user_id, request=request.model_dump())
    except RunnerError as exc:
        raise HTTPException(status_code=int(exc.status_code), detail=str(exc.detail)) from exc
    return await _stream_task(task.task_id, after_seq=0, request=http_request)
