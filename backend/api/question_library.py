from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.question_library_schemas import (
    QuestionLibraryBulkDeleteRequest,
    QuestionLibraryCommitPreviewRequest,
    QuestionLibraryRegenerateSectionRequest,
    QuestionLibraryCrawlRequest,
    QuestionLibraryGenerateRequest,
    QuestionLibraryLatestPendingPreviewResponse,
    QuestionLibraryPreviewResponse,
    QuestionLibraryCommitPreviewResponse,
    QuestionLibraryScoreRequest,
)
from backend.api.question_evaluate import evaluate_generated_question_review
from backend.core.llm_client import is_llm_configured
from backend.core.settings import LESSON_PLAN_MODEL
from backend.crawler_manager import get_crawler
from backend.database.models import (
    bulk_delete_question_library_items,
    get_latest_study_archive,
    get_latest_study_archive_for_subject,
    get_question_cache,
    get_question_library_item,
    list_question_library_items,
    set_hidden,
    set_starred,
    upsert_question_cache,
    upsert_question_library_items,
)
from backend.database.repositories.tasks import (
    list_task_events as db_list_task_events,
)
from backend.database.repositories.tasks import (
    append_task_event as db_append_task_event,
)
from backend.database.repositories.tasks import (
    update_task_status as db_update_task_status,
)
from backend.database.repositories.tasks import (
    upsert_task as db_upsert_task,
)
from backend.question_library.generation import (
    build_ai_question_id,
    build_source_pack,
    generate_questions,
    regenerate_question_section,
)
from backend.question_library.preview_store import (
    find_latest_pending_preview,
    find_preview_by_session_id,
    find_session_by_preview_id,
    load_preview,
    load_session,
    new_preview_id,
    new_session_id,
    save_session,
    save_preview,
    list_sessions as list_saved_sessions,
)
from backend.question_library.scoring import apply_score_and_hide, score_stem_with_llm
from backend.question_library.task_manager import QuestionLibraryTask, QuestionLibraryTaskManager

router = APIRouter(prefix="/question-library", tags=["question-library"], dependencies=[Depends(require_auth)])

_tasks = QuestionLibraryTaskManager(
    max_tasks=int(os.getenv("QUESTION_LIBRARY_MAX_TASKS") or "50"),
    task_ttl_s=int(os.getenv("QUESTION_LIBRARY_TASK_TTL_S") or str(60 * 60)),
    max_events_per_task=int(os.getenv("QUESTION_LIBRARY_TASK_MAX_EVENTS") or "8000"),
)


_DIFFICULTY_HINTS = {"简单", "基础", "中等", "困难", "较难", "较易", "偏难", "偏易", "易", "难"}
_QUESTION_TYPE_HINTS = {"选择题", "解答题", "填空题", "判断题", "证明题", "综合题", "问答题"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


_REVIEW_STATUSES = {"pending_review", "in_review", "approved", "rejected", "confirmed", "committed"}


def _normalize_review_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in _REVIEW_STATUSES:
        return raw
    return "pending_review"


def _normalize_draft_questions(input_value: Any) -> List[dict]:
    out: List[dict] = []
    for item in input_value or []:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "").strip()
        if not qid:
            continue
        review = item.get("review") if isinstance(item.get("review"), dict) else None
        out.append(
            {
                "question_id": qid,
                "stem": str(item.get("stem") or "").strip(),
                "answer": str(item.get("answer") or "").strip(),
                "analysis": str(item.get("analysis") or "").strip(),
                "keep": bool(item.get("keep", True)),
                "review_status": _normalize_review_status(item.get("review_status")),
                "review": dict(review) if review else None,
            }
        )
    return out


def _serialize_session_preview(obj: dict) -> dict:
    drafts = _normalize_draft_questions(obj.get("draft_questions") if isinstance(obj, dict) else [])
    return {
        "preview_id": str((obj or {}).get("preview_id") or "").strip(),
        "session_id": str((obj or {}).get("session_id") or "").strip(),
        "task_id": str((obj or {}).get("task_id") or "").strip(),
        "subject": str((obj or {}).get("subject") or "").strip(),
        "topic": str((obj or {}).get("topic") or "").strip(),
        "mode": str((obj or {}).get("mode") or "standard").strip() or "standard",
        "count": len(drafts),
        "draft_questions": drafts,
    }


def _find_draft_index(items: List[dict], question_id: str) -> int:
    target_id = str(question_id or "").strip()
    for index, item in enumerate(items):
        if str((item or {}).get("question_id") or "").strip() == target_id:
            return index
    return -1


def _merge_drafts(existing: List[dict], incoming: List[dict]) -> List[dict]:
    merged = [dict(item) for item in _normalize_draft_questions(existing)]
    for item in _normalize_draft_questions(incoming):
        index = _find_draft_index(merged, str(item.get("question_id") or ""))
        if index >= 0:
            merged[index] = {**merged[index], **item}
        else:
            merged.append(dict(item))
    return merged


def _serialize_session_summary(session: dict) -> dict:
    drafts = _normalize_draft_questions(session.get("draft_questions") if isinstance(session, dict) else [])
    reasoning_blocks = session.get("reasoning_blocks") if isinstance(session.get("reasoning_blocks"), list) else []
    return {
        "session_id": str((session or {}).get("session_id") or "").strip(),
        "preview_id": str((session or {}).get("preview_id") or "").strip(),
        "status": str((session or {}).get("status") or "").strip(),
        "mode": str((session or {}).get("mode") or "standard").strip() or "standard",
        "subject": str((session or {}).get("subject") or "").strip(),
        "topic": str((session or {}).get("topic") or "").strip(),
        "count": len(drafts),
        "task_ids": list(session.get("task_ids") or []) if isinstance(session.get("task_ids"), list) else [],
        "latest_task_id": str((session or {}).get("latest_task_id") or "").strip(),
        "updated_at_s": float((session or {}).get("updated_at_s") or (session or {}).get("created_at_s") or 0.0),
        "created_at_s": float((session or {}).get("created_at_s") or 0.0),
        "reasoning_blocks_count": len(reasoning_blocks),
        "confirmed_question_ids": list(session.get("confirmed_question_ids") or [])
        if isinstance(session.get("confirmed_question_ids"), list)
        else [],
        "stop_requested": bool((session or {}).get("stop_requested")),
    }


async def _load_session_task_events(user_id: str, task_ids: List[str]) -> List[dict]:
    events: List[dict] = []
    for task_id in task_ids[-6:]:
        if not str(task_id or "").strip():
            continue
        try:
            task_events = await db_list_task_events(user_id=user_id, task_id=str(task_id), after_seq=0, limit=500)
        except Exception:
            task_events = []
        for event in task_events or []:
            if isinstance(event, dict):
                events.append(dict(event))
    events.sort(key=lambda item: (str(item.get("created_at") or ""), int(item.get("seq") or 0)))
    return events[-500:]


def _ensure_session(
    *,
    session_id: str,
    user_id: str,
    preview_id: str,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    mode: str,
    count: int,
    use_study_archive: bool,
    grade_id: str,
    textbook_version_id: str,
    knowledge_point_ids: List[str],
    knowledge_points: List[str],
    task_id: str,
    stream_reasoning: bool,
) -> dict:
    existing = load_session(session_id) if session_id else None
    session = dict(existing or {})
    session["session_id"] = session_id
    session["user_id"] = user_id
    session["preview_id"] = preview_id
    preview_ids = list(session.get("preview_ids") or []) if isinstance(session.get("preview_ids"), list) else []
    if preview_id and preview_id not in preview_ids:
        preview_ids.append(preview_id)
    session["preview_ids"] = preview_ids
    session["status"] = str(session.get("status") or "pending_review").strip() or "pending_review"
    session["mode"] = str(mode or session.get("mode") or "standard").strip() or "standard"
    session["subject"] = subject
    session["topic"] = topic
    session["difficulty"] = difficulty
    session["question_type"] = question_type
    session["count"] = int(count or 0)
    session["use_study_archive"] = bool(use_study_archive)
    session["grade_id"] = str(grade_id or "").strip()
    session["textbook_version_id"] = str(textbook_version_id or "").strip()
    session["knowledge_point_ids"] = [str(item or "").strip() for item in (knowledge_point_ids or []) if str(item or "").strip()]
    session["knowledge_points"] = [str(item or "").strip() for item in (knowledge_points or []) if str(item or "").strip()]
    session["stream_reasoning"] = bool(stream_reasoning)
    session["stop_requested"] = False if task_id else bool(session.get("stop_requested"))
    task_ids = list(session.get("task_ids") or []) if isinstance(session.get("task_ids"), list) else []
    if task_id and task_id not in task_ids:
        task_ids.append(task_id)
    session["task_ids"] = task_ids
    session["latest_task_id"] = task_ids[-1] if task_ids else ""
    session.setdefault("reasoning_blocks", [])
    session.setdefault("draft_questions", [])
    session.setdefault("confirmed_question_ids", [])
    return save_session(session)


def _touch_session_status(session: dict, *, status: str) -> dict:
    next_session = dict(session or {})
    next_session["status"] = str(status or "").strip()
    return save_session(next_session)


def _normalize_topic_key(topic: str) -> str:
    """
    The frontend sometimes passes the whole mission text as `topic` (including output rules).

    For LLM prompting / study-archive lookup, we want a short knowledge-point key instead of
    a verbose instruction blob.
    """

    raw = str(topic or "").strip()
    if not raw:
        return ""

    # Strip "output requirements" suffixes to reduce prompt length and avoid exact-match misses.
    for marker in ("输出要求", "LaTeX 公式规范", "LaTeX公式规范", "Output requirements"):
        idx = raw.find(marker)
        if idx >= 0:
            raw = raw[:idx].strip()
            break

    first_line = ""
    for ln in raw.splitlines():
        line = ln.strip()
        if line:
            first_line = line
            break
    if not first_line:
        first_line = raw

    # If it looks like a comma-separated token list, drop difficulty/type tokens.
    if any(sep in first_line for sep in (",", "，", ";", "；", "+", "＋", "/", "|", "、")):
        normalized = first_line
        for sep in ("，", ";", "；", "+", "＋", "/", "|", "、"):
            normalized = normalized.replace(sep, ",")
        parts = [p.strip() for p in normalized.split(",") if p.strip()]
        kept: list[str] = []
        for p in parts:
            if p in _DIFFICULTY_HINTS:
                continue
            if any(h in p for h in _QUESTION_TYPE_HINTS):
                continue
            if "LaTeX" in p or "公式" in p or "输出要求" in p:
                continue
            kept.append(p)
        if kept:
            first_line = "，".join(kept)

    return first_line[:120].strip()


def _infer_question_type_from_topic(topic: str) -> str:
    raw = str(topic or "")
    if "选择题" in raw and "解答题" in raw:
        return "选择题+解答题"
    for hint in ("选择题", "解答题", "填空题", "判断题", "证明题", "综合题", "问答题"):
        if hint in raw:
            return hint
    return ""


def _sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


async def _stream_task(task_id: str, *, after_seq: int) -> StreamingResponse:
    heartbeat_s = float(os.getenv("QUESTION_LIBRARY_SSE_HEARTBEAT_S") or "4.0")

    async def event_generator():
        async for event in _tasks.stream(task_id, after_seq=after_seq, heartbeat_s=heartbeat_s):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@router.get("/items", response_model=dict)
async def list_items(
    subject: str = Query(""),
    origin: str = Query(""),
    hidden: str = Query("0"),
    q: str = Query(""),
    min_score: Optional[int] = Query(None),
    sort: str = Query("updated_at"),
    order: str = Query("desc"),
    limit: int = Query(50),
    offset: int = Query(0),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return await list_question_library_items(
        user_id=user_id,
        subject=subject,
        origin=origin,
        hidden=hidden if hidden in {"0", "1", "all"} else "0",
        q=q,
        min_score=min_score,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/items/{question_id}", response_model=dict)
async def get_item_detail(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    item = await get_question_library_item(user_id=user_id, question_id=question_id)
    if not item:
        raise HTTPException(status_code=404, detail="not_found")

    cache = await get_question_cache(question_ids=[str(question_id or "").strip()])
    return {"library_item": item, "question_cache": cache.get(str(question_id or "").strip())}


@router.post("/items/{question_id}/hide", response_model=dict)
async def hide_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await set_hidden(user_id=user_id, question_id=question_id, hidden=True)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/unhide", response_model=dict)
async def unhide_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await set_hidden(user_id=user_id, question_id=question_id, hidden=False)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/star", response_model=dict)
async def star_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await set_starred(user_id=user_id, question_id=question_id, starred=True)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/unstar", response_model=dict)
async def unstar_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await set_starred(user_id=user_id, question_id=question_id, starred=False)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/bulk-delete", response_model=dict)
async def bulk_delete_items(request: QuestionLibraryBulkDeleteRequest, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ids = [str(x or "").strip() for x in (request.question_ids or []) if str(x or "").strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(status_code=400, detail="question_ids_required")
    if len(ids) > 500:
        raise HTTPException(status_code=400, detail="too_many_ids")

    deleted = await bulk_delete_question_library_items(user_id=user_id, question_ids=ids)
    return {"success": True, "deleted": deleted}


@router.post("/items/{question_id}/export-to-basket", response_model=dict)
async def export_item_to_basket(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    qid = str(question_id or "").strip()
    if not qid:
        raise HTTPException(status_code=400, detail="missing_question_id")
    if not qid.isdigit():
        raise HTTPException(status_code=400, detail="question_id_not_numeric")

    item = await get_question_library_item(user_id=user_id, question_id=qid)
    if not item:
        raise HTTPException(status_code=404, detail="not_found")

    cache = await get_question_cache(question_ids=[qid])
    q = cache.get(qid) or {}
    subject = str(item.get("subject") or q.get("subject") or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="subject_required")

    def _kp_text(rec: dict) -> str:
        raw = str(rec.get("knowledge_points_json") or "").strip()
        kp = str(rec.get("knowledge_point") or "").strip()
        try:
            obj = json.loads(raw) if raw else []
        except Exception:
            obj = []
        parts = []
        if kp:
            parts.append(kp)
        if isinstance(obj, list):
            for x in obj[:12]:
                if isinstance(x, str) and x.strip():
                    parts.append(x.strip())
        uniq = []
        seen = set()
        for p in parts:
            if p in seen:
                continue
            seen.add(p)
            uniq.append(p)
        return "、".join(uniq[:12])

    detail = {
        "question_id": qid,
        "type": str(q.get("question_type") or "").strip() or "解答题",
        "difficulty": str(q.get("difficulty") or "").strip() or "中等",
        "source": str(q.get("source") or "").strip() or "本地题库",
        "knowledge_points": _kp_text(q),
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
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    payload = await _tasks.status_payload(task_id=task_id, user_id=user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="task_not_found")
    return payload


@router.get("/tasks/{task_id}/stream")
async def stream_task(
    task_id: str, after_seq: int = Query(0, ge=0), user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    task = await _tasks.get_task(task_id)
    if not task or task.user_id != user_id:
        raise HTTPException(status_code=404, detail="task_not_found")
    return await _stream_task(task.task_id, after_seq=after_seq)


@router.get("/previews/{preview_id}", response_model=QuestionLibraryPreviewResponse)
async def get_preview(preview_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")

    obj = load_preview(pid)
    if not obj or str(obj.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="preview_not_found")
    return {"success": True, **_serialize_session_preview(obj)}


@router.get("/previews/latest/pending", response_model=QuestionLibraryLatestPendingPreviewResponse)
async def get_latest_pending_preview(user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    obj = find_latest_pending_preview(user_id)
    if not obj:
        return {"success": True, "preview": None}
    return {"success": True, "preview": _serialize_session_preview(obj)}


@router.get("/sessions", response_model=dict)
async def list_question_library_sessions(user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    sessions = [_serialize_session_summary(item) for item in list_saved_sessions(user_id, include_archived=True, limit=60)]
    return {"success": True, "sessions": sessions}


@router.get("/sessions/{session_id}", response_model=dict)
async def get_question_library_session(session_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    sid = str(session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="missing_session_id")

    session = load_session(sid)
    if not session or str(session.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="session_not_found")

    task_ids = list(session.get("task_ids") or []) if isinstance(session.get("task_ids"), list) else []
    task_events = await _load_session_task_events(user_id, task_ids)
    payload = dict(session)
    payload["draft_questions"] = _normalize_draft_questions(session.get("draft_questions"))
    payload["task_events"] = task_events
    return {"success": True, "session": payload}


@router.post("/sessions/{session_id}/stop", response_model=dict)
async def stop_question_library_session(session_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    session = load_session(session_id)
    if not session or str(session.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="session_not_found")
    session = dict(session)
    session["stop_requested"] = True
    session["status"] = "stopped"
    save_session(session)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "status": "stopped"}


@router.post("/sessions/{session_id}/archive", response_model=dict)
async def archive_question_library_session(session_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    session = load_session(session_id)
    if not session or str(session.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="session_not_found")
    session = dict(session)
    session["status"] = "archived"
    save_session(session)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "status": "archived"}


@router.post("/previews/{preview_id}/commit", response_model=QuestionLibraryCommitPreviewResponse)
async def commit_preview(
    preview_id: str, request: QuestionLibraryCommitPreviewRequest, user: dict = Depends(require_auth)
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")

    obj = load_preview(pid)
    if not obj or str(obj.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="preview_not_found")

    status = str(obj.get("status") or "").strip().lower()
    if status == "committed":
        raise HTTPException(status_code=409, detail="preview_already_committed")

    subject = str(obj.get("subject") or "").strip()
    topic = str(obj.get("topic") or "").strip()
    difficulty = str(obj.get("difficulty") or "").strip()
    question_type = str(obj.get("question_type") or "").strip()

    preview_items = _normalize_draft_questions(obj.get("draft_questions") if isinstance(obj.get("draft_questions"), list) else [])
    preview_by_id: dict[str, dict] = {}
    for it in preview_items:
        if not isinstance(it, dict):
            continue
        qid = str(it.get("question_id") or "").strip()
        if qid:
            preview_by_id[qid] = dict(it)

    accepted_payload = []
    inserted_ids: list[str] = []
    for q in request.questions or []:
        qid = str(q.question_id or "").strip()
        if not qid or not q.keep:
            continue
        if qid not in preview_by_id:
            continue
        review_status = _normalize_review_status(preview_by_id[qid].get("review_status"))
        if review_status not in {"approved", "confirmed"}:
            raise HTTPException(status_code=409, detail="review_required_before_commit")
        stem = str(q.stem or "").strip()
        answer = str(q.answer or "").strip()
        analysis = str(q.analysis or "").strip()
        if not stem or not answer or not analysis:
            continue
        inserted_ids.append(qid)
        accepted_payload.append(
            {
                "question_id": qid,
                "subject": subject,
                "question_type": question_type,
                "difficulty": difficulty,
                "knowledge_point": topic,
                "source_url": "",
                "stem": stem,
                "answer": answer,
                "analysis": analysis,
            }
        )

    if not accepted_payload:
        raise HTTPException(status_code=400, detail="no_questions_selected")

    await upsert_question_cache(accepted_payload)
    await upsert_question_library_items(
        user_id=user_id,
        items=[{"question_id": qid, "subject": subject, "origin": "ai"} for qid in inserted_ids],
    )

    obj = dict(obj)
    obj["status"] = "committed"
    obj["committed_at_s"] = time.time()
    obj["committed"] = {
        "inserted": len(inserted_ids),
        "question_ids": inserted_ids,
    }
    committed_set = set(inserted_ids)
    updated_preview_items: List[dict] = []
    for item in preview_items:
        next_item = dict(item)
        qid = str(next_item.get("question_id") or "").strip()
        if qid in committed_set:
            next_item["review_status"] = "committed"
        updated_preview_items.append(next_item)
    obj["draft_questions"] = updated_preview_items
    save_preview(obj)

    session = find_session_by_preview_id(user_id, pid)
    if isinstance(session, dict):
        next_session = dict(session)
        next_session["status"] = "committed"
        next_session["draft_questions"] = updated_preview_items
        next_session["committed_question_ids"] = inserted_ids
        confirmed_ids = list(next_session.get("confirmed_question_ids") or []) if isinstance(next_session.get("confirmed_question_ids"), list) else []
        next_session["confirmed_question_ids"] = [item for item in confirmed_ids if item in committed_set] or inserted_ids
        save_session(next_session)

    return {
        "success": True,
        "preview_id": pid,
        "inserted": len(inserted_ids),
        "subject": subject,
        "count": len(inserted_ids),
        "question_ids": inserted_ids,
    }


@router.post("/previews/{preview_id}/discard", response_model=dict)
async def discard_preview(preview_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")

    obj = load_preview(pid)
    if not obj or str(obj.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="preview_not_found")
    obj = dict(obj)
    obj["status"] = "archived_discarded"
    obj["discarded_at_s"] = time.time()
    save_preview(obj)

    session = find_session_by_preview_id(user_id, pid)
    if isinstance(session, dict):
        next_session = dict(session)
        next_session["status"] = "archived_discarded"
        next_session["stop_requested"] = True
        save_session(next_session)

    return {"success": True}


def _load_owned_session_or_404(session_id: str, user_id: str) -> dict:
    session = load_session(session_id)
    if not session or str(session.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="session_not_found")
    return dict(session)


def _persist_session_draft_update(session: dict, draft: dict) -> dict:
    drafts = _normalize_draft_questions(session.get("draft_questions"))
    index = _find_draft_index(drafts, str(draft.get("question_id") or ""))
    if index < 0:
        raise HTTPException(status_code=404, detail="session_question_not_found")
    drafts[index] = {**drafts[index], **dict(draft)}
    session["draft_questions"] = drafts
    saved = save_session(session)

    preview_id = str(saved.get("preview_id") or "").strip()
    preview = load_preview(preview_id) if preview_id else None
    if isinstance(preview, dict):
        preview_drafts = _normalize_draft_questions(preview.get("draft_questions"))
        preview_index = _find_draft_index(preview_drafts, str(draft.get("question_id") or ""))
        if preview_index >= 0:
            preview_drafts[preview_index] = {**preview_drafts[preview_index], **dict(draft)}
            preview["draft_questions"] = preview_drafts
            save_preview(preview)
    return saved


@router.post("/sessions/{session_id}/questions/{question_id}/review", response_model=dict)
async def review_session_question(session_id: str, question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    session = _load_owned_session_or_404(session_id, user_id)
    drafts = _normalize_draft_questions(session.get("draft_questions"))
    index = _find_draft_index(drafts, question_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="session_question_not_found")

    draft = dict(drafts[index])
    review = await evaluate_generated_question_review(
        subject=str(session.get("subject") or "").strip(),
        stem=str(draft.get("stem") or "").strip(),
        answer=str(draft.get("answer") or "").strip(),
        analysis=str(draft.get("analysis") or "").strip(),
        requirements=f"目标难度：{str(session.get('difficulty') or '').strip()}；题型：{str(session.get('question_type') or '').strip()}",
        model=str(LESSON_PLAN_MODEL or "").strip(),
    )
    draft["review"] = review
    if _normalize_review_status(draft.get("review_status")) in {"approved", "rejected", "confirmed", "committed"}:
        draft["review_status"] = _normalize_review_status(draft.get("review_status"))
    else:
        draft["review_status"] = "in_review"

    session = _persist_session_draft_update(session, draft)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "question": draft}


@router.post("/sessions/{session_id}/questions/{question_id}/approve", response_model=dict)
async def approve_session_question(session_id: str, question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    session = _load_owned_session_or_404(session_id, user_id)
    drafts = _normalize_draft_questions(session.get("draft_questions"))
    index = _find_draft_index(drafts, question_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="session_question_not_found")

    draft = dict(drafts[index])
    if not isinstance(draft.get("review"), dict):
        review = await evaluate_generated_question_review(
            subject=str(session.get("subject") or "").strip(),
            stem=str(draft.get("stem") or "").strip(),
            answer=str(draft.get("answer") or "").strip(),
            analysis=str(draft.get("analysis") or "").strip(),
            requirements=f"目标难度：{str(session.get('difficulty') or '').strip()}；题型：{str(session.get('question_type') or '').strip()}",
            model=str(LESSON_PLAN_MODEL or "").strip(),
        )
        draft["review"] = review
    draft["review_status"] = "approved"
    session = _persist_session_draft_update(session, draft)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "question": draft}


@router.post("/sessions/{session_id}/questions/{question_id}/reject", response_model=dict)
async def reject_session_question(session_id: str, question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    session = _load_owned_session_or_404(session_id, user_id)
    drafts = _normalize_draft_questions(session.get("draft_questions"))
    index = _find_draft_index(drafts, question_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="session_question_not_found")

    draft = dict(drafts[index])
    if not isinstance(draft.get("review"), dict):
        review = await evaluate_generated_question_review(
            subject=str(session.get("subject") or "").strip(),
            stem=str(draft.get("stem") or "").strip(),
            answer=str(draft.get("answer") or "").strip(),
            analysis=str(draft.get("analysis") or "").strip(),
            requirements=f"目标难度：{str(session.get('difficulty') or '').strip()}；题型：{str(session.get('question_type') or '').strip()}",
            model=str(LESSON_PLAN_MODEL or "").strip(),
        )
        draft["review"] = review
    draft["review_status"] = "rejected"
    session = _persist_session_draft_update(session, draft)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "question": draft}


@router.post("/sessions/{session_id}/questions/{question_id}/confirm", response_model=dict)
async def confirm_session_question(session_id: str, question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    session = _load_owned_session_or_404(session_id, user_id)
    drafts = _normalize_draft_questions(session.get("draft_questions"))
    index = _find_draft_index(drafts, question_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="session_question_not_found")

    draft = dict(drafts[index])
    if _normalize_review_status(draft.get("review_status")) != "approved":
        raise HTTPException(status_code=409, detail="review_required_before_confirm")
    draft["review_status"] = "confirmed"
    confirmed_ids = list(session.get("confirmed_question_ids") or []) if isinstance(session.get("confirmed_question_ids"), list) else []
    if question_id not in confirmed_ids:
        confirmed_ids.append(question_id)
    session["confirmed_question_ids"] = confirmed_ids
    session = _persist_session_draft_update(session, draft)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "question": draft}


@router.post("/sessions/{session_id}/questions/{question_id}/unconfirm", response_model=dict)
async def unconfirm_session_question(session_id: str, question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    session = _load_owned_session_or_404(session_id, user_id)
    drafts = _normalize_draft_questions(session.get("draft_questions"))
    index = _find_draft_index(drafts, question_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="session_question_not_found")

    draft = dict(drafts[index])
    if _normalize_review_status(draft.get("review_status")) == "confirmed":
        draft["review_status"] = "approved"
    confirmed_ids = [item for item in (session.get("confirmed_question_ids") or []) if str(item or "").strip() and str(item or "").strip() != question_id]
    session["confirmed_question_ids"] = confirmed_ids
    session = _persist_session_draft_update(session, draft)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "question": draft}


@router.post("/previews/{preview_id}/regenerate-section")
async def regenerate_preview_section(
    preview_id: str, request: QuestionLibraryRegenerateSectionRequest, user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")

    obj = load_preview(pid)
    if not isinstance(obj, dict):
        raise HTTPException(status_code=404, detail="preview_not_found")
    if str(obj.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="preview_not_found")
    if str(obj.get("status") or "").strip().lower() == "committed":
        raise HTTPException(status_code=409, detail="preview_already_committed")

    question_id = str(request.question_id or "").strip()
    section_key = str(request.section_key or "").strip()
    if not question_id:
        raise HTTPException(status_code=400, detail="missing_question_id")
    if section_key not in {"stem", "answer", "analysis"}:
        raise HTTPException(status_code=400, detail="invalid_section_key")

    preview_items = obj.get("draft_questions") if isinstance(obj.get("draft_questions"), list) else []
    target_index = -1
    target_question: dict | None = None
    for index, item in enumerate(preview_items):
        if not isinstance(item, dict):
            continue
        if str(item.get("question_id") or "").strip() != question_id:
            continue
        target_index = index
        target_question = dict(item)
        break

    if target_index < 0 or not isinstance(target_question, dict):
        raise HTTPException(status_code=404, detail="preview_question_not_found")

    async def event_generator():
        seq = 0

        def format_event(event_type: str, data: dict) -> str:
            nonlocal seq
            seq += 1
            payload = {"type": event_type, "seq": seq, "data": data}
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        try:
            yield format_event(
                "progress",
                {
                    "question_id": question_id,
                    "section_key": section_key,
                    "stage": "加载草稿上下文",
                    "progress": 15,
                },
            )

            preview_topic_raw = str(obj.get("topic") or "").strip()
            preview_topic_key = _normalize_topic_key(preview_topic_raw) or preview_topic_raw
            study_markdown = str(obj.get("study_markdown") or "").strip()
            if not study_markdown:
                try:
                    archive = await get_latest_study_archive(
                        user_id=user_id,
                        subject=str(obj.get("subject") or "").strip(),
                        topic=preview_topic_key,
                    )
                except Exception:
                    archive = None
                if not isinstance(archive, dict):
                    # The preview topic is often a free-form mission string (not the canonical StudyArchive.topic).
                    # Fall back to the latest archive for the subject so "use study archive" still works.
                    try:
                        archive = await get_latest_study_archive_for_subject(
                            user_id=user_id, subject=str(obj.get("subject") or "").strip()
                        )
                    except Exception:
                        archive = None
                if isinstance(archive, dict):
                    study_markdown = str(archive.get("markdown") or "").strip()

            yield format_event(
                "progress",
                {
                    "question_id": question_id,
                    "section_key": section_key,
                    "stage": "调用模型重写 section",
                    "progress": 55,
                },
            )

            content = await regenerate_question_section(
                subject=str(obj.get("subject") or "").strip(),
                topic=preview_topic_key,
                difficulty=str(obj.get("difficulty") or "").strip(),
                question_type=str(obj.get("question_type") or "").strip(),
                study_markdown=study_markdown,
                section_key=section_key,
                stem=str(target_question.get("stem") or "").strip(),
                answer=str(target_question.get("answer") or "").strip(),
                analysis=str(target_question.get("analysis") or "").strip(),
            )
            if not content:
                raise RuntimeError("section_regeneration_failed")

            target_question[section_key] = content
            preview_items[target_index] = target_question
            obj["draft_questions"] = preview_items
            if study_markdown and not str(obj.get("study_markdown") or "").strip():
                obj["study_markdown"] = study_markdown
            save_preview(obj)
            session = find_session_by_preview_id(user_id, pid)
            if isinstance(session, dict):
                session["draft_questions"] = _merge_drafts(session.get("draft_questions"), [target_question])
                save_session(session)

            done_payload = {
                "preview_id": pid,
                "question_id": question_id,
                "section_key": section_key,
                "content": content,
                "draft_question": target_question,
            }
            yield format_event("done", done_payload)
        except Exception as exc:
            yield format_event(
                "error",
                {
                    "question_id": question_id,
                    "section_key": section_key,
                    "message": str(exc) or "section_regeneration_failed",
                },
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=_sse_headers())


@router.post("/crawl")
async def crawl_and_save(request: QuestionLibraryCrawlRequest, user: dict = Depends(require_auth)) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    subject = (request.subject or "").strip()
    edu_level = (request.edu_level or "").strip()
    query = (request.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query_required")

    try:
        limit = max(1, min(int(request.limit or 30), 200))
    except Exception:
        limit = 30
    try:
        max_pages = max(1, min(int(request.max_pages or 2), 50))
    except Exception:
        max_pages = 2
    try:
        min_quality_score = max(0, min(int(request.min_quality_score or 0), 100))
    except Exception:
        min_quality_score = 0

    difficulty_value_min = request.difficulty_value_min
    difficulty_value_max = request.difficulty_value_max
    try:
        if difficulty_value_min is not None:
            difficulty_value_min = float(difficulty_value_min)
    except Exception:
        difficulty_value_min = None
    try:
        if difficulty_value_max is not None:
            difficulty_value_max = float(difficulty_value_max)
    except Exception:
        difficulty_value_max = None

    if difficulty_value_min is not None:
        difficulty_value_min = max(0.0, min(1.0, difficulty_value_min))
    if difficulty_value_max is not None:
        difficulty_value_max = max(0.0, min(1.0, difficulty_value_max))
    if (
        difficulty_value_min is not None
        and difficulty_value_max is not None
        and difficulty_value_min > difficulty_value_max
    ):
        difficulty_value_min, difficulty_value_max = difficulty_value_max, difficulty_value_min

    require_difficulty_value = bool(request.require_difficulty_value) and (
        difficulty_value_min is not None or difficulty_value_max is not None
    )

    difficulty = (request.difficulty or "").strip()
    question_type = (request.question_type or "").strip()

    task_id = (request.task_id or "").strip() or f"ql_crawl_{uuid.uuid4().hex[:12]}"

    async def runner_factory(task: QuestionLibraryTask) -> None:
        try:
            await _tasks.append_event(
                task,
                {
                    "type": "step",
                    "step": {
                        "id": "crawl",
                        "title": "爬取入库",
                        "status": "running",
                        "startTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "toolName": "question_library_crawl",
                        "input": {
                            "taskId": task.task_id,
                            "subject": subject,
                            "edu_level": edu_level,
                            "query": query,
                            "difficulty": difficulty,
                            "question_type": question_type,
                            "limit": limit,
                            "max_pages": max_pages,
                            "min_quality_score": min_quality_score,
                            "difficulty_value_min": difficulty_value_min,
                            "difficulty_value_max": difficulty_value_max,
                            "require_difficulty_value": require_difficulty_value,
                        },
                    },
                },
            )

            crawler = await get_crawler(subject=subject, edu_level=edu_level, strict=True)
            res = await crawler.search_by_keyword(
                keyword=query,
                subject=subject,
                edu_level=edu_level,
                limit=limit,
                difficulty=difficulty,
                question_type=question_type,
                max_pages=max_pages,
                min_quality_score=min_quality_score,
                difficulty_value_min=difficulty_value_min,
                difficulty_value_max=difficulty_value_max,
                require_difficulty_value=require_difficulty_value,
                parse_content=True,
            )

            if not bool(res.get("success")):
                raise RuntimeError(str(res.get("error") or "crawl_failed"))

            questions = res.get("questions") if isinstance(res.get("questions"), list) else []
            total = len(questions)
            inserted = 0
            qids: list[str] = []

            for i, q in enumerate(questions, start=1):
                if task.status != "running":
                    break
                if not isinstance(q, dict):
                    continue

                qid = str(q.get("question_id") or "").strip()
                stem = str(q.get("stem") or "").strip()
                if not qid or not stem:
                    continue

                # For crawled questions we only persist the stem + metadata (no answer/analysis).
                cache_item = {
                    "question_id": qid,
                    "subject": subject,
                    "question_type": str(q.get("question_type") or q.get("type") or "").strip(),
                    "difficulty": str(q.get("difficulty") or "").strip(),
                    "knowledge_point": str(q.get("knowledge_point") or "").strip(),
                    "source_url": str(q.get("source_url") or "").strip(),
                    "stem": stem,
                    "stem_fingerprint": str(q.get("stem_fingerprint") or q.get("stem_fp") or "").strip(),
                    "difficulty_value": q.get("difficulty_value"),
                    "quality_score": int(q.get("quality_score") or 0),
                    "quality_flags": q.get("quality_flags") or "",
                    "knowledge_points_json": q.get("knowledge_points_json") or q.get("knowledge_points") or "",
                    "source": str(q.get("source") or "").strip(),
                    "date": str(q.get("date") or "").strip(),
                }
                await upsert_question_cache([cache_item])
                await upsert_question_library_items(
                    user_id=user_id,
                    items=[{"question_id": qid, "subject": subject, "origin": "crawled"}],
                )

                inserted += 1
                qids.append(qid)

                await _tasks.append_event(
                    task,
                    {
                        "type": "item_saved",
                        "data": {
                            "item": {
                                "question_id": qid,
                                "subject": subject,
                                "origin": "crawled",
                                "hidden": False,
                                "stem": stem,
                            }
                        },
                    },
                )

                pct = int((i / max(1, total)) * 100)
                await _tasks.append_event(task, {"type": "progress", "data": {"progress": pct}})

            await _tasks.append_event(
                task,
                {
                    "type": "done",
                    "data": {
                        "success": True,
                        "inserted": inserted,
                        "subject": subject,
                        "count": len(qids),
                        "question_ids": qids,
                    },
                },
            )
            await _tasks.complete_task(task)
        except asyncio.CancelledError:
            await _tasks.fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            await _tasks.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await _tasks.fail_task(task, "Task ended unexpectedly")

    task = await _tasks.create_task(
        task_id=task_id, user_id=user_id, kind="crawl", request=request.model_dump(), runner_factory=runner_factory
    )  # type: ignore[attr-defined]
    return await _stream_task(task.task_id, after_seq=0)


@router.post("/generate")
async def generate_and_save(
    request: QuestionLibraryGenerateRequest, user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    if not is_llm_configured():
        raise HTTPException(status_code=500, detail="llm_not_configured")

    subject = (request.subject or "").strip()
    topic_raw = (request.topic or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="subject_required")
    if not topic_raw:
        raise HTTPException(status_code=400, detail="topic_required")

    difficulty = (request.difficulty or "").strip()
    question_type = (request.question_type or "").strip()
    topic_key = _normalize_topic_key(topic_raw) or topic_raw
    session_id = str(request.session_id or "").strip()
    mode = str(request.mode or "standard").strip() or "standard"
    if mode not in {"standard", "infinite"}:
        mode = "standard"
    append_mode = bool(request.append)
    stream_reasoning = bool(request.stream_reasoning)
    grade_id = str(request.grade_id or "").strip()
    textbook_version_id = str(request.textbook_version_id or "").strip()
    knowledge_point_ids = [str(item or "").strip() for item in (request.knowledge_point_ids or []) if str(item or "").strip()]
    knowledge_points = [str(item or "").strip() for item in (request.knowledge_points or []) if str(item or "").strip()]
    if not question_type:
        inferred = _infer_question_type_from_topic(topic_raw)
        if inferred:
            question_type = inferred

    try:
        count = max(1, min(int(request.count or 5), 10))
    except Exception:
        count = 5

    task_id = (request.task_id or "").strip() or f"ql_gen_{uuid.uuid4().hex[:12]}"
    use_archive = bool(request.use_study_archive)
    existing_session = load_session(session_id) if session_id else None
    if session_id and existing_session and str(existing_session.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="session_not_found")
    if not session_id:
        session_id = new_session_id()

    existing_preview = find_preview_by_session_id(user_id, session_id) if append_mode and session_id else None
    preview_id = (
        str((existing_session or {}).get("preview_id") or "").strip()
        if append_mode and isinstance(existing_session, dict)
        else ""
    ) or str((existing_preview or {}).get("preview_id") or "").strip() or new_preview_id()

    current_session = _ensure_session(
        session_id=session_id,
        user_id=user_id,
        preview_id=preview_id,
        subject=subject,
        topic=topic_raw,
        difficulty=difficulty,
        question_type=question_type,
        mode=mode,
        count=count,
        use_study_archive=use_archive,
        grade_id=grade_id,
        textbook_version_id=textbook_version_id,
        knowledge_point_ids=knowledge_point_ids,
        knowledge_points=knowledge_points,
        task_id=task_id,
        stream_reasoning=stream_reasoning,
    )
    current_session["status"] = "running"
    save_session(current_session)

    started_at = _utcnow()
    await db_upsert_task(
        user_id=user_id,
        task_id=task_id,
        task_type="question_library_generate",
        title=f"AI 出题：{subject} {topic_key}".strip(),
        status="running",
        progress=0.0,
        request=request.model_dump(),
        started_at=started_at,
    )

    async def runner_factory(task: QuestionLibraryTask) -> None:
        def _now_iso() -> str:
            return _utcnow().isoformat(timespec="milliseconds").replace("+00:00", "Z")

        stage_descriptions = {
            "source_pack": "整理出题上下文，构建一个包含主题、难度与题型约束的素材包。",
            "spec_search": "扩展题目规格树，筛出更有区分度和新意的候选方向。",
            "draft_realization": "按规格生成题干、答案与解析草稿，并保留代表样例。",
            "judge": "通过求解、歧义检查与评审筛掉低质题、套路题和不自洽题。",
            "final_selection": "从通过判题的候选中选出最终入围草稿。",
            "pending_review": "题目草稿已生成，进入预览审核；审核通过后才会写入本地题库。",
        }
        stage_labels = {
            "source_pack": "素材整理",
            "spec_search": "规格搜索",
            "draft_realization": "草稿生成",
            "judge": "判题筛选",
            "final_selection": "终选入围",
            "pending_review": "待审核预览",
        }
        stage_progress_defaults = {
            "source_pack": 5.0,
            "spec_search": 20.0,
            "draft_realization": 55.0,
            "judge": 80.0,
            "final_selection": 92.0,
            "pending_review": 96.0,
        }
        stage_started_at: Dict[str, str] = {}
        stage_state: Dict[str, Dict[str, Any]] = {}
        active_stage_id: str | None = None

        async def _emit_progress(
            progress: float,
            *,
            stage_id: str,
            stage_label: str,
            stats: Optional[dict] = None,
            sample: Optional[dict] = None,
        ) -> None:
            payload: Dict[str, Any] = {
                "progress": float(progress),
                "stage": str(stage_label or "").strip(),
                "stage_id": str(stage_id or "").strip(),
                "stage_label": str(stage_label or "").strip(),
            }
            if isinstance(stats, dict) and stats:
                payload["stats"] = stats
            if isinstance(sample, dict) and sample:
                payload["sample"] = sample
            await _tasks.append_event(task, {"type": "progress", "data": payload})
            try:
                await db_append_task_event(
                    user_id=user_id,
                    task_id=task_id,
                    event_type="progress",
                    payload=payload,
                    progress=float(progress),
                )
            except Exception:
                pass

        def _build_stage_output(
            *,
            stage_id: str,
            stage_label: str,
            summary: str = "",
            stats: Optional[dict] = None,
            sample: Optional[dict] = None,
        ) -> dict:
            output: Dict[str, Any] = {
                "stage_id": str(stage_id or "").strip(),
                "stage_label": str(stage_label or "").strip(),
            }
            if summary:
                output["summary"] = summary
            if isinstance(stats, dict) and stats:
                output["stats"] = stats
            if isinstance(sample, dict) and sample:
                output["sample"] = sample
            return output

        async def _emit_step(step: dict) -> None:
            await _tasks.append_event(task, {"type": "step", "step": step})
            try:
                await db_append_task_event(user_id=user_id, task_id=task_id, event_type="step", payload={"step": step})
            except Exception:
                pass

        async def _emit_reasoning_event(event: dict) -> None:
            if not isinstance(event, dict):
                return
            event_type = str(event.get("type") or "reasoning_delta").strip() or "reasoning_delta"
            payload = {key: value for key, value in event.items() if key != "type"}
            await _tasks.append_event(task, {"type": event_type, "data": payload})
            try:
                await db_append_task_event(user_id=user_id, task_id=task_id, event_type=event_type, payload=payload)
            except Exception:
                pass

            current_session = load_session(session_id)
            if not isinstance(current_session, dict):
                return

            if event_type == "reasoning_delta":
                blocks = list(current_session.get("reasoning_blocks") or []) if isinstance(current_session.get("reasoning_blocks"), list) else []
                blocks.append(
                    {
                        "id": f"reason-{uuid.uuid4().hex[:12]}",
                        "task_id": task_id,
                        "stage_id": str(payload.get("stage_id") or "").strip(),
                        "stage_label": str(payload.get("stage_label") or "").strip(),
                        "source": str(payload.get("source") or "").strip() or "trace",
                        "content": str(payload.get("content") or "").strip(),
                        "created_at": _utcnow().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    }
                )
                current_session["reasoning_blocks"] = blocks[-600:]
            elif event_type == "reasoning_status":
                statuses = list(current_session.get("reasoning_statuses") or []) if isinstance(current_session.get("reasoning_statuses"), list) else []
                statuses.append(
                    {
                        "task_id": task_id,
                        "stage_id": str(payload.get("stage_id") or "").strip(),
                        "stage_label": str(payload.get("stage_label") or "").strip(),
                        "mode": str(payload.get("mode") or "").strip() or "trace",
                        "message": str(payload.get("message") or "").strip(),
                        "created_at": _utcnow().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    }
                )
                current_session["reasoning_statuses"] = statuses[-200:]
            save_session(current_session)

        async def _update_stage_step(
            *,
            stage_id: str,
            stage_label: str,
            status: str,
            progress: float,
            summary: str = "",
            stats: Optional[dict] = None,
            sample: Optional[dict] = None,
        ) -> None:
            start_time = stage_started_at.get(stage_id) or _now_iso()
            stage_started_at.setdefault(stage_id, start_time)
            snapshot = stage_state.get(stage_id) or {}
            summary_value = str(summary or snapshot.get("summary") or "").strip()
            stats_value = stats if isinstance(stats, dict) and stats else snapshot.get("stats")
            sample_value = sample if isinstance(sample, dict) and sample else snapshot.get("sample")
            stage_state[stage_id] = {
                "summary": summary_value,
                "stats": stats_value,
                "sample": sample_value,
            }
            step = {
                "id": f"stage:{stage_id}",
                "title": stage_label,
                "status": status,
                "toolName": "thinking",
                "startTime": start_time,
                "input": {"stage_id": stage_id, "stage_label": stage_label},
                "output": _build_stage_output(
                    stage_id=stage_id,
                    stage_label=stage_label,
                    summary=summary_value,
                    stats=stats_value if isinstance(stats_value, dict) else None,
                    sample=sample_value if isinstance(sample_value, dict) else None,
                ),
            }
            if status == "completed":
                step["endTime"] = _now_iso()
            await _emit_step(step)
            await _emit_progress(
                progress,
                stage_id=stage_id,
                stage_label=stage_label,
                stats=stats,
                sample=sample,
            )

        async def _switch_stage(
            stage_id: str,
            *,
            progress: Optional[float] = None,
            stats: Optional[dict] = None,
            sample: Optional[dict] = None,
        ) -> None:
            nonlocal active_stage_id
            normalized_stage = str(stage_id or "").strip()
            if not normalized_stage:
                return

            label = stage_labels.get(normalized_stage) or normalized_stage
            summary = stage_descriptions.get(normalized_stage) or ""
            progress_value = float(progress if progress is not None else stage_progress_defaults.get(normalized_stage, 0.0))

            if active_stage_id and active_stage_id != normalized_stage:
                prev_label = stage_labels.get(active_stage_id) or active_stage_id
                prev_summary = stage_descriptions.get(active_stage_id) or ""
                await _update_stage_step(
                    stage_id=active_stage_id,
                    stage_label=prev_label,
                    status="completed",
                    progress=float(stage_progress_defaults.get(active_stage_id, progress_value)),
                    summary=prev_summary,
                )

            active_stage_id = normalized_stage
            await _update_stage_step(
                stage_id=normalized_stage,
                stage_label=label,
                status="running",
                progress=progress_value,
                summary=summary,
                stats=stats,
                sample=sample,
            )
            if not stream_reasoning:
                await _emit_reasoning_event(
                    {
                        "type": "reasoning_status",
                        "stage_id": normalized_stage,
                        "stage_label": label,
                        "mode": "trace",
                        "message": "当前模型未启用原始 reasoning，已降级为事件级 trace。",
                    }
                )
                if summary:
                    await _emit_reasoning_event(
                        {
                            "type": "reasoning_delta",
                            "stage_id": normalized_stage,
                            "stage_label": label,
                            "source": "trace",
                            "content": summary,
                        }
                    )

        async def _complete_active_stage(*, stats: Optional[dict] = None, sample: Optional[dict] = None) -> None:
            nonlocal active_stage_id
            if not active_stage_id:
                return
            stage_id = active_stage_id
            label = stage_labels.get(stage_id) or stage_id
            summary = stage_descriptions.get(stage_id) or ""
            await _update_stage_step(
                stage_id=stage_id,
                stage_label=label,
                status="completed",
                progress=float(stage_progress_defaults.get(stage_id, 100.0)),
                summary=summary,
                stats=stats,
                sample=sample,
            )
            active_stage_id = None

        try:
            await _switch_stage("source_pack")

            study_markdown = ""
            if use_archive:
                try:
                    archive = await get_latest_study_archive(user_id=user_id, subject=subject, topic=topic_key)
                except Exception:
                    archive = None
                if not isinstance(archive, dict):
                    # The frontend passes the whole mission text as `topic`, so exact topic matching can miss.
                    # Use the latest subject-level archive as a best-effort "recent study materials" fallback.
                    try:
                        archive = await get_latest_study_archive_for_subject(user_id=user_id, subject=subject)
                    except Exception:
                        archive = None
                if isinstance(archive, dict):
                    study_markdown = str(archive.get("markdown") or "")

            source_pack = await build_source_pack(
                study_markdown,
                subject,
                topic_key,
                stream_reasoning=stream_reasoning,
                on_reasoning_event=_emit_reasoning_event,
            )
            await _update_stage_step(
                stage_id="source_pack",
                stage_label=stage_labels["source_pack"],
                status="completed",
                progress=stage_progress_defaults["source_pack"],
                summary=stage_descriptions["source_pack"],
                stats={
                    "use_study_archive": use_archive,
                    "study_markdown_chars": len(study_markdown),
                    "facts": len(source_pack.get("facts") or []),
                    "skills": len(source_pack.get("skills") or []),
                    "common_mistakes": len(source_pack.get("common_mistakes") or []),
                    "forbidden_patterns": len(source_pack.get("forbidden_patterns") or []),
                },
                sample={
                    "facts": list(source_pack.get("facts") or [])[:3],
                    "skills": list(source_pack.get("skills") or [])[:3],
                },
            )
            active_stage_id = None

            async def _handle_generation_stage(event: dict) -> None:
                if not isinstance(event, dict):
                    return
                phase = str(event.get("phase") or "").strip()
                if not phase:
                    return
                stats = event.get("stats") if isinstance(event.get("stats"), dict) else None
                sample = event.get("sample") if isinstance(event.get("sample"), dict) else None
                await _switch_stage(
                    phase,
                    progress=float(event.get("progress") or stage_progress_defaults.get(phase, 0.0)),
                    stats=stats,
                    sample=sample,
                )

            finals = await generate_questions(
                source_pack=source_pack,
                count=count,
                difficulty=difficulty,
                question_type=question_type,
                on_stage_event=_handle_generation_stage,
                on_reasoning_event=_emit_reasoning_event,
                stream_reasoning=stream_reasoning,
                config=None,
            )
            await _complete_active_stage()

            drafts: list[dict] = []
            for q in finals[:count]:
                if task.status != "running":
                    break
                if not isinstance(q, dict):
                    continue
                stem = str(q.get("stem") or "").strip()
                answer = str(q.get("answer") or "").strip()
                analysis = str(q.get("analysis") or "").strip()
                if not stem or not answer or not analysis:
                    continue
                qid = build_ai_question_id(suffix=uuid.uuid4().hex[:8])
                drafts.append(
                    {
                        "question_id": qid,
                        "stem": stem,
                        "answer": answer,
                        "analysis": analysis,
                        "keep": True,
                    }
                )

            if not drafts:
                raise RuntimeError("no_questions_generated")

            await _switch_stage(
                "pending_review",
                stats={"draft_count": len(drafts)},
                sample={
                    "question_id": str((drafts[0] or {}).get("question_id") or ""),
                    "stem_preview": str((drafts[0] or {}).get("stem") or "")[:120],
                }
                if drafts
                else None,
            )

            existing_preview = load_preview(preview_id) if append_mode else None
            merged_drafts = _merge_drafts(
                existing_preview.get("draft_questions") if isinstance(existing_preview, dict) else [],
                drafts,
            )
            save_preview(
                {
                    "preview_id": preview_id,
                    "session_id": session_id,
                    "mode": mode,
                    "status": "pending_review",
                    "user_id": user_id,
                    "task_id": task_id,
                    "subject": subject,
                    "topic": topic_raw,
                    "difficulty": difficulty,
                    "question_type": question_type,
                    "study_markdown": study_markdown,
                    "draft_questions": merged_drafts,
                }
            )
            current_session = _ensure_session(
                session_id=session_id,
                user_id=user_id,
                preview_id=preview_id,
                subject=subject,
                topic=topic_raw,
                difficulty=difficulty,
                question_type=question_type,
                mode=mode,
                count=count,
                use_study_archive=use_archive,
                grade_id=grade_id,
                textbook_version_id=textbook_version_id,
                knowledge_point_ids=knowledge_point_ids,
                knowledge_points=knowledge_points,
                task_id=task_id,
                stream_reasoning=stream_reasoning,
            )
            current_session["status"] = "pending_review"
            current_session["draft_questions"] = merged_drafts
            save_session(current_session)
            await _complete_active_stage(
                stats={"draft_count": len(merged_drafts), "preview_id": preview_id},
                sample={
                    "question_id": str((merged_drafts[0] or {}).get("question_id") or ""),
                    "stem_preview": str((merged_drafts[0] or {}).get("stem") or "")[:120],
                }
                if merged_drafts
                else None,
            )

            done_payload = {
                "success": True,
                "session_id": session_id,
                "preview_id": preview_id,
                "subject": subject,
                "topic": topic_raw,
                "mode": mode,
                "count": len(merged_drafts),
                "draft_questions": merged_drafts,
            }
            await _tasks.append_event(task, {"type": "done", "data": done_payload})
            try:
                await db_append_task_event(user_id=user_id, task_id=task_id, event_type="done", payload=done_payload)
                await db_update_task_status(
                    user_id=user_id,
                    task_id=task_id,
                    status="completed",
                    progress=100.0,
                    result={
                        "session_id": session_id,
                        "preview_id": preview_id,
                        "subject": subject,
                        "topic": topic_raw,
                        "count": len(merged_drafts),
                    },
                    ended_at=_utcnow(),
                )
            except Exception:
                pass
            await _tasks.complete_task(task)
        except asyncio.CancelledError:
            if active_stage_id:
                await _update_stage_step(
                    stage_id=active_stage_id,
                    stage_label=stage_labels.get(active_stage_id) or active_stage_id,
                    status="paused",
                    progress=float(stage_progress_defaults.get(active_stage_id, 0.0)),
                    summary="任务已取消。",
                )
            await _tasks.fail_task(task, "Task cancelled")
            try:
                await db_update_task_status(
                    user_id=user_id,
                    task_id=task_id,
                    status="canceled",
                    error={"message": "Task cancelled"},
                    ended_at=_utcnow(),
                )
            except Exception:
                pass
            current_session = load_session(session_id)
            if isinstance(current_session, dict):
                current_session["status"] = "stopped"
                current_session["stop_requested"] = True
                save_session(current_session)
            raise
        except Exception as exc:  # pragma: no cover
            if active_stage_id:
                await _update_stage_step(
                    stage_id=active_stage_id,
                    stage_label=stage_labels.get(active_stage_id) or active_stage_id,
                    status="failed",
                    progress=float(stage_progress_defaults.get(active_stage_id, 0.0)),
                    summary=f"阶段执行失败：{str(exc)}",
                )
            await _tasks.fail_task(task, str(exc))
            try:
                await db_append_task_event(
                    user_id=user_id,
                    task_id=task_id,
                    event_type="error",
                    payload={"error": {"message": str(exc)}},
                )
                await db_update_task_status(
                    user_id=user_id,
                    task_id=task_id,
                    status="failed",
                    error={"message": str(exc)},
                    ended_at=_utcnow(),
                )
            except Exception:
                pass
            current_session = load_session(session_id)
            if isinstance(current_session, dict):
                current_session["status"] = "failed"
                save_session(current_session)
        finally:
            if task.status == "running":
                if active_stage_id:
                    await _update_stage_step(
                        stage_id=active_stage_id,
                        stage_label=stage_labels.get(active_stage_id) or active_stage_id,
                        status="failed",
                        progress=float(stage_progress_defaults.get(active_stage_id, 0.0)),
                        summary="任务意外终止。",
                    )
                await _tasks.fail_task(task, "Task ended unexpectedly")
                try:
                    await db_update_task_status(
                        user_id=user_id,
                        task_id=task_id,
                        status="failed",
                        error={"message": "Task ended unexpectedly"},
                        ended_at=_utcnow(),
                    )
                except Exception:
                    pass

    task = await _tasks.create_task(
        task_id=task_id,
        user_id=user_id,
        kind="generate",
        request=request.model_dump(),
        runner_factory=runner_factory,
    )
    return await _stream_task(task.task_id, after_seq=0)


@router.post("/score")
async def score_question_library(
    request: QuestionLibraryScoreRequest, user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    if not is_llm_configured():
        raise HTTPException(status_code=500, detail="llm_not_configured")

    subject = (request.subject or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="subject_required")

    try:
        limit = max(1, min(int(request.limit or 50), 500))
    except Exception:
        limit = 50

    only_unscored = bool(request.only_unscored)
    task_id = (request.task_id or "").strip() or f"ql_score_{uuid.uuid4().hex[:12]}"

    threshold = int(os.getenv("QUESTION_LIBRARY_HIDE_THRESHOLD") or "70")
    model = str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini"

    async def runner_factory(task: QuestionLibraryTask) -> None:
        try:
            await _tasks.append_event(task, {"type": "progress", "data": {"progress": 5, "stage": "Load"}})

            # Pull a visible batch from the library and filter unscored if requested.
            batch = await list_question_library_items(
                user_id=user_id,
                subject=subject,
                origin="crawled",
                hidden="0",
                limit=min(200, max(50, limit)),
                offset=0,
                sort="updated_at",
                order="desc",
            )
            items = batch.get("items") if isinstance(batch, dict) else []
            if not isinstance(items, list):
                items = []

            qids: list[str] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                qid = str(it.get("question_id") or "").strip()
                if not qid:
                    continue
                if only_unscored and it.get("ai_score") is not None:
                    continue
                qids.append(qid)
                if len(qids) >= limit:
                    break

            if not qids:
                await _tasks.append_event(
                    task,
                    {
                        "type": "done",
                        "data": {"success": True, "scored": 0, "hidden": 0, "subject": subject, "count": 0},
                    },
                )
                await _tasks.complete_task(task)
                return

            cache = await get_question_cache(question_ids=qids)

            scored = 0
            hidden_n = 0
            total = len(qids)
            await _tasks.append_event(task, {"type": "progress", "data": {"progress": 10, "stage": "Score"}})

            for idx, qid in enumerate(qids, start=1):
                if task.status != "running":
                    break
                stem = str((cache.get(qid) or {}).get("stem") or "").strip()
                if not stem:
                    continue

                res = await score_stem_with_llm(subject=subject, stem=stem, model=model)
                overall = int(res.get("overall_score") or 0)
                verdict = str(res.get("verdict") or "").strip()
                dims = list(res.get("dimensions") or [])
                summary = str(res.get("summary") or "").strip()

                await apply_score_and_hide(
                    user_id=user_id,
                    question_id=qid,
                    overall_score=overall,
                    verdict=verdict,
                    dimensions=[x for x in dims if isinstance(x, dict)],
                    summary=summary,
                    threshold=threshold,
                )

                scored += 1
                if overall < threshold:
                    hidden_n += 1

                await _tasks.append_event(
                    task,
                    {
                        "type": "item_saved",
                        "data": {
                            "item": {
                                "question_id": qid,
                                "subject": subject,
                                "origin": "crawled",
                                "ai_score": overall,
                                "ai_verdict": verdict,
                                "ai_summary": summary,
                                "hidden": overall < threshold,
                                "stem": stem,
                            }
                        },
                    },
                )

                pct = 10 + int((idx / max(1, total)) * 88)
                await _tasks.append_event(
                    task, {"type": "progress", "data": {"progress": min(98, pct), "stage": "Score"}}
                )

            await _tasks.append_event(
                task,
                {
                    "type": "done",
                    "data": {
                        "success": True,
                        "subject": subject,
                        "count": scored,
                        "scored": scored,
                        "hidden": hidden_n,
                        "threshold": threshold,
                    },
                },
            )
            await _tasks.complete_task(task)
        except asyncio.CancelledError:
            await _tasks.fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            await _tasks.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await _tasks.fail_task(task, "Task ended unexpectedly")

    task = await _tasks.create_task(
        task_id=task_id,
        user_id=user_id,
        kind="score",
        request=request.model_dump(),
        runner_factory=runner_factory,
    )
    return await _stream_task(task.task_id, after_seq=0)
