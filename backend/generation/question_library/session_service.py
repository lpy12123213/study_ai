from __future__ import annotations

import json
import time
from typing import List

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from backend.api.question_evaluate import evaluate_generated_question_review
from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MODEL
from backend.database.repositories.question.question_cache import upsert_question_cache
from backend.database.repositories.question.question_library import upsert_question_library_items
from backend.database.repositories.system.tasks import list_task_events as db_list_task_events
from backend.generation.question_library.generation import regenerate_question_section
from backend.generation.question_library.preview_store import (
    delete_preview,
    find_latest_pending_preview,
    find_session_by_preview_id,
    load_preview,
    load_session,
    save_preview,
    save_session,
)
from backend.generation.question_library.preview_store import (
    list_sessions as list_saved_sessions,
)
from backend.generation.question_library.session_utils import (
    committed_ids_from_drafts,
    confirmed_ids_from_drafts,
    derive_review_container_status,
    merge_practice_state,
    normalize_draft_questions,
    normalize_practice_attempts,
    normalize_review_status,
    resolve_requested_count,
    serialize_session_preview,
    serialize_session_summary,
)

logger = get_logger(__name__)

_COMMIT_VALIDATION_FLAGS = (
    "scope_ok",
    "answer_correct",
    "answer_analysis_consistent",
    "conditions_sufficient",
    "unambiguous",
    "transfer_valid",
    "intuition_aligned",
    "structural_depth",
    "request_aligned",
)


def _require_commit_ready_intuition_packet(draft: dict, *, allow_partial_questions: bool) -> None:
    """Keep AI drafts behind the same hard gate used during generation.

    Media imports do not carry an intuition packet and remain on their existing
    review path. AI drafts fail closed so an old, regenerated, or otherwise
    unvalidated packet cannot be committed by a later approval endpoint.
    """

    if allow_partial_questions:
        return

    packet = draft.get("intuition_packet") if isinstance(draft.get("intuition_packet"), dict) else None
    validation = packet.get("validation") if isinstance(packet, dict) and isinstance(packet.get("validation"), dict) else None
    if not isinstance(validation, dict):
        raise HTTPException(status_code=409, detail="intuition_validation_required")

    status = str(validation.get("status") or "").strip().lower()
    if status != "passed" or not all(validation.get(name) is True for name in _COMMIT_VALIDATION_FLAGS):
        raise HTTPException(status_code=409, detail="intuition_validation_failed")


async def list_question_library_sessions(*, user_id: str) -> dict:
    sessions = [
        serialize_session_summary(item)
        for item in list_saved_sessions(user_id, include_archived=True, limit=60)
        if isinstance(item, dict)
    ]
    return {"success": True, "sessions": sessions}


async def get_question_library_session(*, user_id: str, session_id: str) -> dict:
    sid = str(session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="missing_session_id")

    session = load_session(sid)
    if not session or str(session.get("user_id") or "").strip() != str(user_id or "").strip():
        raise HTTPException(status_code=404, detail="session_not_found")

    task_ids = list(session.get("task_ids") or []) if isinstance(session.get("task_ids"), list) else []
    task_events = await _load_session_task_events(str(user_id or "").strip(), task_ids)
    payload = dict(session)
    drafts = normalize_draft_questions(session.get("draft_questions"))
    draft_count = len(drafts)
    payload["draft_questions"] = drafts
    payload["count"] = draft_count
    payload["requested_count"] = resolve_requested_count(session, draft_count=draft_count)
    payload["draft_count"] = draft_count
    payload["practice_attempts"] = normalize_practice_attempts(session.get("practice_attempts"))
    payload["task_events"] = task_events
    return {"success": True, "session": payload}


async def stop_question_library_session(*, user_id: str, session_id: str) -> dict:
    session = load_session(session_id)
    if not session or str(session.get("user_id") or "").strip() != str(user_id or "").strip():
        raise HTTPException(status_code=404, detail="session_not_found")
    session = dict(session)
    session["stop_requested"] = True
    session["status"] = "stopped"
    save_session(session)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "status": "stopped"}


async def archive_question_library_session(*, user_id: str, session_id: str) -> dict:
    session = load_session(session_id)
    if not session or str(session.get("user_id") or "").strip() != str(user_id or "").strip():
        raise HTTPException(status_code=404, detail="session_not_found")
    session = dict(session)
    session["status"] = "archived"
    save_session(session)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "status": "archived"}


def get_latest_pending_preview(*, user_id: str) -> dict:
    obj = find_latest_pending_preview(user_id)
    if not obj:
        return {"success": True, "preview": None}
    return {"success": True, "preview": serialize_session_preview(obj)}


async def commit_preview_to_library(
    *,
    user_id: str,
    preview_id: str,
    questions: List[dict],
) -> dict:
    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")

    obj = load_preview(pid)
    if not obj or str(obj.get("user_id") or "").strip() != str(user_id or "").strip():
        raise HTTPException(status_code=404, detail="preview_not_found")

    status = str(obj.get("status") or "").strip().lower()
    if status == "committed":
        raise HTTPException(status_code=409, detail="preview_already_committed")

    subject = str(obj.get("subject") or "").strip()
    topic = str(obj.get("topic") or "").strip()
    difficulty = str(obj.get("difficulty") or "").strip()
    question_type = str(obj.get("question_type") or "").strip()
    source_type = str(obj.get("source_type") or "").strip()
    allow_partial_questions = source_type == "media_import"
    origin = "media" if allow_partial_questions else "ai"

    preview_items = normalize_draft_questions(obj.get("draft_questions") if isinstance(obj.get("draft_questions"), list) else [])
    preview_by_id: dict[str, dict] = {}
    for it in preview_items:
        if not isinstance(it, dict):
            continue
        qid = str(it.get("question_id") or "").strip()
        if qid:
            preview_by_id[qid] = dict(it)

    accepted_payload = []
    inserted_ids: list[str] = []
    selected_ids: list[str] = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("question_id") or "").strip()
        if not qid or not bool(q.get("keep", True)):
            continue
        if qid not in preview_by_id:
            continue
        review_status = normalize_review_status(preview_by_id[qid].get("review_status"))
        # Simplified review flow: committing selected questions is the only required confirmation.
        # We still block explicitly rejected drafts to avoid accidental inclusion.
        if review_status == "rejected":
            raise HTTPException(status_code=409, detail="rejected_question_cannot_commit")
        if qid not in selected_ids:
            selected_ids.append(qid)
        if review_status == "committed":
            continue
        canonical = preview_by_id[qid]
        _require_commit_ready_intuition_packet(canonical, allow_partial_questions=allow_partial_questions)
        stem = str(canonical.get("stem") or "").strip()
        answer = str(canonical.get("answer") or "").strip()
        analysis = str(canonical.get("analysis") or "").strip()
        for key, canonical_value in (("stem", stem), ("answer", answer), ("analysis", analysis)):
            submitted_value = str(q.get(key) or "").strip()
            if submitted_value and submitted_value != canonical_value:
                raise HTTPException(status_code=409, detail="question_content_changed_after_validation")
        if not stem or ((not allow_partial_questions) and (not answer or not analysis)):
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
                **(
                    {"intuition_packet": dict(preview_by_id[qid]["intuition_packet"])}
                    if isinstance(preview_by_id[qid].get("intuition_packet"), dict)
                    and preview_by_id[qid].get("intuition_packet")
                    else {}
                ),
            }
        )

    if not selected_ids:
        raise HTTPException(status_code=400, detail="no_questions_selected")

    if accepted_payload:
        await upsert_question_cache(accepted_payload)
        await upsert_question_library_items(
            user_id=user_id,
            items=[{"question_id": qid, "subject": subject, "origin": origin} for qid in inserted_ids],
        )

    obj = dict(obj)
    committed_set = set(selected_ids)
    updated_preview_items: List[dict] = []
    for item in preview_items:
        next_item = dict(item)
        qid = str(next_item.get("question_id") or "").strip()
        if qid in committed_set:
            next_item["review_status"] = "committed"
        updated_preview_items.append(next_item)
    obj["draft_questions"] = updated_preview_items
    obj["status"] = derive_review_container_status(updated_preview_items, current_status=str(obj.get("status") or ""))
    obj["committed"] = {
        "inserted": len(committed_ids_from_drafts(updated_preview_items)),
        "question_ids": committed_ids_from_drafts(updated_preview_items),
    }
    if str(obj.get("status") or "").strip().lower() == "committed":
        obj["committed_at_s"] = time.time()
    save_preview(obj)

    session = find_session_by_preview_id(user_id, pid)
    if isinstance(session, dict):
        next_session = dict(session)
        next_session["draft_questions"] = updated_preview_items
        _sync_session_review_state(next_session)

    return {
        "success": True,
        "preview_id": pid,
        "inserted": len(inserted_ids),
        "subject": subject,
        "count": len(selected_ids),
        "question_ids": selected_ids,
    }


async def discard_preview(*, user_id: str, preview_id: str) -> dict:
    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")

    obj = load_preview(pid)
    if not obj or str(obj.get("user_id") or "").strip() != str(user_id or "").strip():
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
    if not session or str(session.get("user_id") or "").strip() != str(user_id or "").strip():
        raise HTTPException(status_code=404, detail="session_not_found")
    return dict(session)


def _persist_session_draft_update(session: dict, draft: dict) -> dict:
    drafts = normalize_draft_questions(session.get("draft_questions"))
    index = _find_draft_index(drafts, str(draft.get("question_id") or ""))
    if index < 0:
        raise HTTPException(status_code=404, detail="session_question_not_found")
    drafts[index] = {**drafts[index], **dict(draft)}
    session["draft_questions"] = drafts
    saved = save_session(session)

    preview_id = str(saved.get("preview_id") or "").strip()
    preview = load_preview(preview_id) if preview_id else None
    if isinstance(preview, dict):
        preview_drafts = normalize_draft_questions(preview.get("draft_questions"))
        preview_index = _find_draft_index(preview_drafts, str(draft.get("question_id") or ""))
        if preview_index >= 0:
            preview_drafts[preview_index] = {**preview_drafts[preview_index], **dict(draft)}
            preview["draft_questions"] = preview_drafts
            save_preview(preview)
    return saved


def _find_draft_index(items: List[dict], question_id: str) -> int:
    target_id = str(question_id or "").strip()
    for index, item in enumerate(items):
        if str((item or {}).get("question_id") or "").strip() == target_id:
            return index
    return -1


async def update_session_question_practice_state(
    *,
    user_id: str,
    session_id: str,
    question_id: str,
    patch: dict,
) -> dict:
    session = _load_owned_session_or_404(session_id, user_id)
    qid = str(question_id or "").strip()
    drafts = normalize_draft_questions(session.get("draft_questions"))
    if _find_draft_index(drafts, qid) < 0:
        raise HTTPException(status_code=404, detail="session_question_not_found")

    attempts = normalize_practice_attempts(session.get("practice_attempts"))
    state = merge_practice_state(attempts.get(qid), patch, updated_at_s=time.time())
    attempts[qid] = state
    session["practice_attempts"] = attempts
    saved = save_session(session)
    return {
        "success": True,
        "session_id": str(saved.get("session_id") or ""),
        "question_id": qid,
        "practice_state": state,
    }


def _sync_session_review_state(session: dict) -> dict:
    next_session = dict(session)
    drafts = normalize_draft_questions(next_session.get("draft_questions"))
    next_session["draft_questions"] = drafts
    next_session["confirmed_question_ids"] = confirmed_ids_from_drafts(drafts)
    next_session["committed_question_ids"] = committed_ids_from_drafts(drafts)
    next_session["status"] = derive_review_container_status(drafts, current_status=str(next_session.get("status") or ""))
    if str(next_session.get("status") or "").strip().lower() == "committed":
        next_session["committed_at_s"] = time.time()
    saved_session = save_session(next_session)

    preview_id = str(saved_session.get("preview_id") or "").strip()
    preview = load_preview(preview_id) if preview_id else None
    if not isinstance(preview, dict):
        return saved_session

    next_preview = dict(preview)
    preview_drafts = normalize_draft_questions(next_preview.get("draft_questions"))
    next_preview["draft_questions"] = preview_drafts
    next_preview["status"] = derive_review_container_status(
        preview_drafts, current_status=str(next_preview.get("status") or "")
    )
    committed_ids = committed_ids_from_drafts(preview_drafts)
    next_preview["committed"] = {
        "inserted": len(committed_ids),
        "question_ids": committed_ids,
    }
    if str(next_preview.get("status") or "").strip().lower() == "committed":
        next_preview["committed_at_s"] = time.time()
    save_preview(next_preview)
    return saved_session


async def review_session_question(*, user_id: str, session_id: str, question_id: str) -> dict:
    session = _load_owned_session_or_404(session_id, user_id)
    drafts = normalize_draft_questions(session.get("draft_questions"))
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
    if normalize_review_status(draft.get("review_status")) in {"approved", "rejected", "confirmed", "committed"}:
        draft["review_status"] = normalize_review_status(draft.get("review_status"))
    else:
        draft["review_status"] = "in_review"

    session = _persist_session_draft_update(session, draft)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "question": draft}


async def approve_session_question(*, user_id: str, session_id: str, question_id: str) -> dict:
    session = _load_owned_session_or_404(session_id, user_id)
    drafts = normalize_draft_questions(session.get("draft_questions"))
    index = _find_draft_index(drafts, question_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="session_question_not_found")

    draft = dict(drafts[index])
    draft = await _ensure_session_draft_review(session, draft)

    if normalize_review_status(draft.get("review_status")) == "committed":
        return {"success": True, "session_id": str(session.get("session_id") or ""), "question": draft}

    session, committed_draft = await _commit_single_draft_to_library(user_id=user_id, session=session, draft=draft)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "question": committed_draft}


async def reject_session_question(*, user_id: str, session_id: str, question_id: str) -> dict:
    session = _load_owned_session_or_404(session_id, user_id)
    drafts = normalize_draft_questions(session.get("draft_questions"))
    index = _find_draft_index(drafts, question_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="session_question_not_found")

    draft = dict(drafts[index])
    if normalize_review_status(draft.get("review_status")) == "committed":
        raise HTTPException(status_code=409, detail="question_already_committed")

    draft = await _ensure_session_draft_review(session, draft)
    draft["review_status"] = "rejected"
    session = _persist_session_draft_update(session, draft)
    session = _sync_session_review_state(session)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "question": draft}


async def confirm_session_question(*, user_id: str, session_id: str, question_id: str) -> dict:
    # Current behavior: confirm is identical to approve (commit immediately).
    return await approve_session_question(user_id=user_id, session_id=session_id, question_id=question_id)


async def unconfirm_session_question(*, user_id: str, session_id: str, question_id: str) -> dict:
    session = _load_owned_session_or_404(session_id, user_id)
    drafts = normalize_draft_questions(session.get("draft_questions"))
    index = _find_draft_index(drafts, question_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="session_question_not_found")

    draft = dict(drafts[index])
    status = normalize_review_status(draft.get("review_status"))
    if status == "committed":
        raise HTTPException(status_code=409, detail="question_already_committed")
    if status == "confirmed":
        draft["review_status"] = "approved"
    session = _persist_session_draft_update(session, draft)
    session = _sync_session_review_state(session)
    return {"success": True, "session_id": str(session.get("session_id") or ""), "question": draft}


async def regenerate_preview_section(
    *,
    user_id: str,
    preview_id: str,
    question_id: str,
    section_key: str,
) -> StreamingResponse:
    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")

    obj = load_preview(pid)
    if not isinstance(obj, dict):
        raise HTTPException(status_code=404, detail="preview_not_found")
    if str(obj.get("user_id") or "").strip() != str(user_id or "").strip():
        raise HTTPException(status_code=404, detail="preview_not_found")
    if str(obj.get("status") or "").strip().lower() == "committed":
        raise HTTPException(status_code=409, detail="preview_already_committed")

    qid = str(question_id or "").strip()
    if not qid:
        raise HTTPException(status_code=400, detail="missing_question_id")
    normalized_key = str(section_key or "").strip()
    if normalized_key not in {"stem", "answer", "analysis"}:
        raise HTTPException(status_code=400, detail="invalid_section_key")

    preview_items = obj.get("draft_questions") if isinstance(obj.get("draft_questions"), list) else []
    target_index = -1
    target_question: dict | None = None
    for index, item in enumerate(preview_items):
        if not isinstance(item, dict):
            continue
        if str(item.get("question_id") or "").strip() != qid:
            continue
        target_index = index
        target_question = dict(item)
        break

    if target_index < 0 or not isinstance(target_question, dict):
        raise HTTPException(status_code=404, detail="preview_question_not_found")

    def _sse_headers() -> dict:
        return {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

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
                    "stage": "regenerate_section",
                    "progress": 5,
                    "question_id": qid,
                    "section_key": normalized_key,
                },
            )

            subject = str(obj.get("subject") or "").strip()
            topic = str(obj.get("topic") or "").strip()
            difficulty = str(obj.get("difficulty") or "").strip()
            question_type = str(obj.get("question_type") or "").strip()
            study_markdown = str(obj.get("study_markdown") or "").strip()

            content = await regenerate_question_section(
                subject=subject,
                topic=topic,
                difficulty=difficulty,
                question_type=question_type,
                study_markdown=study_markdown,
                section_key=normalized_key,
                stem=str(target_question.get("stem") or "").strip(),
                answer=str(target_question.get("answer") or "").strip(),
                analysis=str(target_question.get("analysis") or "").strip(),
            )
            content_changed = bool(content) and content != str(target_question.get(normalized_key) or "").strip()
            if content_changed:
                target_question[normalized_key] = content
                # A local content rewrite invalidates the old packet, validation,
                # review, and any learner responses tied to that exact content.
                target_question.pop("intuition_packet", None)
                target_question.pop("quick_validation", None)
                target_question.pop("review", None)
                target_question["review_status"] = "pending_review"

            yield format_event(
                "progress",
                {
                    "stage": "regenerate_section",
                    "progress": 80,
                    "question_id": qid,
                    "section_key": normalized_key,
                },
            )

            preview_items[target_index] = target_question
            obj["draft_questions"] = preview_items
            save_preview(obj)
            session = find_session_by_preview_id(user_id, pid)
            if isinstance(session, dict):
                session_drafts = normalize_draft_questions(session.get("draft_questions"))
                normalized_target_items = normalize_draft_questions([target_question])
                normalized_target = normalized_target_items[0] if normalized_target_items else dict(target_question)
                session_index = next(
                    (
                        index
                        for index, item in enumerate(session_drafts)
                        if str((item or {}).get("question_id") or "").strip() == qid
                    ),
                    -1,
                )
                if session_index >= 0:
                    # Replace the draft instead of shallow-merging it. A changed
                    # section intentionally omits stale packet/review fields.
                    session_drafts[session_index] = dict(normalized_target)
                else:
                    session_drafts.append(dict(normalized_target))
                session["draft_questions"] = session_drafts
                if content_changed:
                    attempts = normalize_practice_attempts(session.get("practice_attempts"))
                    attempts.pop(qid, None)
                    session["practice_attempts"] = attempts
                save_session(session)

            done_payload = {
                "preview_id": pid,
                "question_id": qid,
                "section_key": normalized_key,
                "content": content,
                "draft_question": target_question,
            }
            yield format_event("done", done_payload)
        except Exception as exc:
            logger.exception("question_library_regenerate_section_stream_failed")
            yield format_event(
                "error",
                {
                    "question_id": qid,
                    "section_key": normalized_key,
                    "message": str(exc) or "section_regeneration_failed",
                },
            )


    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=_sse_headers())


async def _load_session_task_events(user_id: str, task_ids: List[str]) -> List[dict]:
    events: List[dict] = []
    for task_id in task_ids[-6:]:
        if not str(task_id or "").strip():
            continue
        try:
            task_events = await db_list_task_events(user_id=user_id, task_id=str(task_id), after_seq=0, limit=500)
        except Exception:
            logger.exception("question_library_session_task_events_load_failed", extra={"task_id": str(task_id)})
            task_events = []
        for event in task_events or []:
            if isinstance(event, dict):
                events.append(dict(event))
    events.sort(key=lambda item: (str(item.get("created_at") or ""), int(item.get("seq") or 0)))
    return events[-500:]


async def _ensure_session_draft_review(session: dict, draft: dict) -> dict:
    if isinstance(draft.get("review"), dict):
        return dict(draft)

    next_draft = dict(draft)
    next_draft["review"] = await evaluate_generated_question_review(
        subject=str(session.get("subject") or "").strip(),
        stem=str(next_draft.get("stem") or "").strip(),
        answer=str(next_draft.get("answer") or "").strip(),
        analysis=str(next_draft.get("analysis") or "").strip(),
        requirements=f"目标难度：{str(session.get('difficulty') or '').strip()}；题型：{str(session.get('question_type') or '').strip()}",
        model=str(LESSON_PLAN_MODEL or "").strip(),
    )
    return next_draft


async def _commit_single_draft_to_library(*, user_id: str, session: dict, draft: dict) -> tuple[dict, dict]:
    qid = str(draft.get("question_id") or "").strip()
    if not qid:
        raise HTTPException(status_code=400, detail="missing_question_id")

    subject = str(session.get("subject") or "").strip()
    topic = str(session.get("topic") or "").strip()
    difficulty = str(session.get("difficulty") or "").strip()
    question_type = str(session.get("question_type") or "").strip()

    stem = str(draft.get("stem") or "").strip()
    answer = str(draft.get("answer") or "").strip()
    analysis = str(draft.get("analysis") or "").strip()
    allow_partial_questions = str(session.get("source_type") or "").strip() == "media_import"
    if not stem or ((not allow_partial_questions) and (not answer or not analysis)):
        raise HTTPException(status_code=400, detail="draft_incomplete_for_commit")
    _require_commit_ready_intuition_packet(draft, allow_partial_questions=allow_partial_questions)

    await upsert_question_cache(
        [
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
                **(
                    {"intuition_packet": dict(draft["intuition_packet"])}
                    if isinstance(draft.get("intuition_packet"), dict) and draft.get("intuition_packet")
                    else {}
                ),
            }
        ]
    )
    await upsert_question_library_items(
        user_id=user_id,
        items=[{"question_id": qid, "subject": subject, "origin": "media" if allow_partial_questions else "ai"}],
    )

    next_draft = dict(draft)
    next_draft["review_status"] = "committed"
    next_draft["keep"] = True

    saved_session = _persist_session_draft_update(session, next_draft)
    saved_session = _sync_session_review_state(saved_session)
    return saved_session, next_draft


async def delete_preview_and_session(*, user_id: str, preview_id: str) -> dict:
    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")
    preview = load_preview(pid)
    if not preview or str(preview.get("user_id") or "").strip() != str(user_id or "").strip():
        raise HTTPException(status_code=404, detail="preview_not_found")
    delete_preview(pid)
    session = find_session_by_preview_id(user_id, pid)
    if isinstance(session, dict):
        session["status"] = "archived_discarded"
        save_session(session)
    return {"success": True}
