from __future__ import annotations

import json
import time
from typing import Any, List

_REVIEW_STATUSES = {"pending_review", "in_review", "approved", "rejected", "confirmed", "committed"}


def normalize_review_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in _REVIEW_STATUSES:
        return raw
    return "pending_review"


def normalize_draft_questions(input_value: Any) -> List[dict]:
    out: List[dict] = []
    for item in input_value or []:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "").strip()
        if not qid:
            continue
        review = item.get("review") if isinstance(item.get("review"), dict) else None
        diagrams = item.get("diagrams")
        normalized_diagrams = None
        if isinstance(diagrams, list):
            normalized_diagrams = [d for d in diagrams if isinstance(d, dict)][:6]
        out.append(
            {
                "question_id": qid,
                "stem": str(item.get("stem") or "").strip(),
                "answer": str(item.get("answer") or "").strip(),
                "analysis": str(item.get("analysis") or "").strip(),
                "keep": bool(item.get("keep", True)),
                "review_status": normalize_review_status(item.get("review_status")),
                "review": dict(review) if review else None,
                **({"diagrams": normalized_diagrams} if normalized_diagrams is not None else {}),
            }
        )
    return out


def serialize_session_preview(obj: dict) -> dict:
    drafts = normalize_draft_questions(obj.get("draft_questions") if isinstance(obj, dict) else [])
    return {
        "preview_id": str((obj or {}).get("preview_id") or "").strip(),
        "session_id": str((obj or {}).get("session_id") or "").strip(),
        "task_id": str((obj or {}).get("task_id") or "").strip(),
        "subject": str((obj or {}).get("subject") or "").strip(),
        "topic": str((obj or {}).get("topic") or "").strip(),
        "mode": str((obj or {}).get("mode") or "standard").strip() or "standard",
        "difficulty": str((obj or {}).get("difficulty") or "").strip(),
        "question_type": str((obj or {}).get("question_type") or "").strip(),
        "use_study_archive": bool((obj or {}).get("use_study_archive", True)),
        "use_reference_questions": bool((obj or {}).get("use_reference_questions", True)),
        "reference_source": str((obj or {}).get("reference_source") or "any").strip() or "any",
        "reference_year_range": str((obj or {}).get("reference_year_range") or "all").strip() or "all",
        "count": len(drafts),
        "draft_questions": drafts,
    }


def serialize_session_summary(session: dict) -> dict:
    drafts = normalize_draft_questions(session.get("draft_questions") if isinstance(session, dict) else [])
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
        "use_reference_questions": bool((session or {}).get("use_reference_questions", True)),
        "reference_source": str((session or {}).get("reference_source") or "any").strip() or "any",
        "reference_year_range": str((session or {}).get("reference_year_range") or "all").strip() or "all",
        "confirmed_question_ids": list(session.get("confirmed_question_ids") or [])
        if isinstance(session.get("confirmed_question_ids"), list)
        else [],
        "stop_requested": bool((session or {}).get("stop_requested")),
    }


def _find_draft_index(items: List[dict], question_id: str) -> int:
    target_id = str(question_id or "").strip()
    for index, item in enumerate(items):
        if str((item or {}).get("question_id") or "").strip() == target_id:
            return index
    return -1


def merge_drafts(existing: List[dict], incoming: List[dict]) -> List[dict]:
    merged = [dict(item) for item in normalize_draft_questions(existing)]
    for item in normalize_draft_questions(incoming):
        index = _find_draft_index(merged, str(item.get("question_id") or ""))
        if index >= 0:
            merged[index] = {**merged[index], **item}
        else:
            merged.append(dict(item))
    return merged


def confirmed_ids_from_drafts(drafts: List[dict]) -> List[str]:
    out: List[str] = []
    for draft in normalize_draft_questions(drafts):
        qid = str(draft.get("question_id") or "").strip()
        status = normalize_review_status(draft.get("review_status"))
        if qid and status in {"confirmed", "committed"} and qid not in out:
            out.append(qid)
    return out


def committed_ids_from_drafts(drafts: List[dict]) -> List[str]:
    out: List[str] = []
    for draft in normalize_draft_questions(drafts):
        qid = str(draft.get("question_id") or "").strip()
        if qid and normalize_review_status(draft.get("review_status")) == "committed" and qid not in out:
            out.append(qid)
    return out


def derive_review_container_status(drafts: List[dict], *, current_status: str) -> str:
    normalized = normalize_draft_questions(drafts)
    if not normalized:
        return str(current_status or "pending_review").strip() or "pending_review"

    statuses = [normalize_review_status(item.get("review_status")) for item in normalized]
    if all(status in {"committed", "rejected"} for status in statuses):
        return "committed" if any(status == "committed" for status in statuses) else "pending_review"

    current = str(current_status or "").strip().lower()
    if current in {"archived_discarded", "archived", "failed"}:
        return current
    return "pending_review"


def draft_identity(item: dict) -> str:
    stem = str((item or {}).get("stem") or "").strip()
    answer = str((item or {}).get("answer") or "").strip()
    analysis = str((item or {}).get("analysis") or "").strip()
    return json.dumps({"stem": stem, "answer": answer, "analysis": analysis}, ensure_ascii=False, sort_keys=True)


def now_iso_z() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
