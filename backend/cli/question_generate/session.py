"""Draft normalisation/merge and preview-store session management.

Pure data helpers plus the thin wrappers over
:mod:`backend.generation.question_library.preview_store` that the CLI uses to
persist sessions, previews and streamed reasoning blocks.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from backend.generation.question_library.generation import build_ai_question_id
from backend.generation.question_library.preview_store import (
    load_session,
    save_preview,
    save_session,
)

from .helpers import _normalize_review_status


def _normalize_draft_questions(input_value: Any) -> List[dict]:
    out: List[dict] = []
    for item in input_value or []:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "").strip()
        if not qid:
            continue
        review = item.get("review") if isinstance(item.get("review"), dict) else None
        difficulty = str(item.get("difficulty") or "").strip()
        judge_score_raw = item.get("judge_score")
        if judge_score_raw is None:
            judge_obj = item.get("judge") if isinstance(item.get("judge"), dict) else None
            if isinstance(judge_obj, dict):
                judge_score_raw = judge_obj.get("overall_score")
        judge_score: Optional[int]
        try:
            judge_score = int(judge_score_raw) if judge_score_raw is not None else None
        except (TypeError, ValueError):
            judge_score = None
        out.append(
            {
                "question_id": qid,
                "difficulty": difficulty,
                "judge_score": judge_score,
                "stem": str(item.get("stem") or "").strip(),
                "answer": str(item.get("answer") or "").strip(),
                "analysis": str(item.get("analysis") or "").strip(),
                "keep": bool(item.get("keep", True)),
                "review_status": _normalize_review_status(item.get("review_status")),
                "review": dict(review) if review else None,
            }
        )
    return out


def _find_draft_index(items: List[dict], question_id: str) -> int:
    target_id = str(question_id or "").strip()
    for index, item in enumerate(items):
        if str((item or {}).get("question_id") or "").strip() == target_id:
            return index
    return -1


def _merge_drafts(existing: Any, incoming: Any) -> List[dict]:
    merged = [dict(item) for item in _normalize_draft_questions(existing)]
    for item in _normalize_draft_questions(incoming):
        index = _find_draft_index(merged, str(item.get("question_id") or ""))
        if index >= 0:
            merged[index] = {**merged[index], **item}
        else:
            merged.append(dict(item))
    return merged


def _draft_identity(item: dict) -> str:
    stem = str((item or {}).get("stem") or "").strip()
    answer = str((item or {}).get("answer") or "").strip()
    analysis = str((item or {}).get("analysis") or "").strip()
    return json.dumps({"stem": stem, "answer": answer, "analysis": analysis}, ensure_ascii=False, sort_keys=True)


def _materialize_draft(item: dict, *, draft_key_to_id: Dict[str, str]) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    stem = str(item.get("stem") or "").strip()
    answer = str(item.get("answer") or "").strip()
    analysis = str(item.get("analysis") or "").strip()
    if not stem or not answer or not analysis:
        return None

    key = _draft_identity(item)
    qid = str(item.get("question_id") or "").strip() or draft_key_to_id.get(key) or build_ai_question_id(
        suffix=uuid.uuid4().hex[:8]
    )
    draft_key_to_id[key] = qid
    review = item.get("review") if isinstance(item.get("review"), dict) else None
    difficulty = str(item.get("difficulty") or "").strip()
    judge_score_raw = item.get("judge_score")
    judge_obj = item.get("judge") if isinstance(item.get("judge"), dict) else None
    if judge_score_raw is None and isinstance(judge_obj, dict):
        judge_score_raw = judge_obj.get("overall_score")
    judge_score: Optional[int]
    try:
        judge_score = int(judge_score_raw) if judge_score_raw is not None else None
    except (TypeError, ValueError):
        judge_score = None
    return {
        "question_id": qid,
        "difficulty": difficulty,
        "judge_score": judge_score,
        "stem": stem,
        "answer": answer,
        "analysis": analysis,
        "keep": bool(item.get("keep", True)),
        "review_status": _normalize_review_status(item.get("review_status")),
        "review": dict(review) if review else None,
    }


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
    use_reference_questions: bool,
    reference_source: str,
    reference_year_range: str,
    stream_reasoning: bool,
    use_mcp_search: bool,
    mcp_search_provider: str,
    mcp_search_mode: str,
    mcp_search_recency_days: int,
    mcp_search_limit: int,
    mcp_search_query: str,
) -> dict:
    existing = load_session(session_id) if session_id else None
    session = dict(existing or {})
    session["session_id"] = session_id
    session["user_id"] = user_id
    session["preview_id"] = preview_id
    session["status"] = str(session.get("status") or "pending_review").strip() or "pending_review"
    session["mode"] = str(mode or session.get("mode") or "standard").strip() or "standard"
    session["subject"] = subject
    session["topic"] = topic
    session["difficulty"] = difficulty
    session["question_type"] = question_type
    session["count"] = int(count or 0)
    session["use_reference_questions"] = bool(use_reference_questions)
    session["reference_source"] = str(reference_source or "any").strip() or "any"
    session["reference_year_range"] = str(reference_year_range or "all").strip() or "all"
    session["stream_reasoning"] = bool(stream_reasoning)
    session["use_mcp_search"] = bool(use_mcp_search)
    session["mcp_search_provider"] = str(mcp_search_provider or "").strip() or "auto"
    session["mcp_search_mode"] = str(mcp_search_mode or "").strip() or "trending"
    session["mcp_search_recency_days"] = int(mcp_search_recency_days or 0) or 180
    session["mcp_search_limit"] = int(mcp_search_limit or 5)
    session["mcp_search_query"] = str(mcp_search_query or "").strip()
    session.setdefault("draft_questions", [])
    session.setdefault("confirmed_question_ids", [])
    session.setdefault("reasoning_blocks", [])
    session.setdefault("stop_requested", False)
    return save_session(session)


def _save_preview_for_session(session: dict, *, preview_status: str) -> None:
    if not isinstance(session, dict):
        return
    preview_id = str(session.get("preview_id") or "").strip()
    if not preview_id:
        return
    save_preview(
        {
            "preview_id": preview_id,
            "session_id": str(session.get("session_id") or "").strip(),
            "mode": str(session.get("mode") or "standard").strip() or "standard",
            "status": str(preview_status or "").strip() or "running",
            "user_id": str(session.get("user_id") or "").strip(),
            "task_id": str(session.get("latest_task_id") or "").strip(),
            "subject": str(session.get("subject") or "").strip(),
            "topic": str(session.get("topic") or "").strip(),
            "difficulty": str(session.get("difficulty") or "").strip(),
            "question_type": str(session.get("question_type") or "").strip(),
            "use_reference_questions": bool(session.get("use_reference_questions", True)),
            "reference_source": str(session.get("reference_source") or "any").strip() or "any",
            "reference_year_range": str(session.get("reference_year_range") or "all").strip() or "all",
            "study_markdown": "",
            "draft_questions": _normalize_draft_questions(session.get("draft_questions")),
        }
    )


def _append_reasoning_block(session: dict, *, stage_id: str, stage_label: str, source: str, content: str) -> dict:
    if not isinstance(session, dict):
        return session
    if not content:
        return session

    blocks = (
        list(session.get("reasoning_blocks") or []) if isinstance(session.get("reasoning_blocks"), list) else []
    )
    if (
        blocks
        and isinstance(blocks[-1], dict)
        and str(blocks[-1].get("stage_id") or "").strip() == stage_id
        and str(blocks[-1].get("source") or "").strip() == source
    ):
        blocks[-1]["content"] = str(blocks[-1].get("content") or "").rstrip() + content
    else:
        blocks.append(
            {
                "id": f"reason-{uuid.uuid4().hex[:12]}",
                "task_id": "tui",
                "stage_id": stage_id,
                "stage_label": stage_label,
                "source": source,
                "content": content,
            }
        )

    # Prevent unbounded growth on disk.
    if len(blocks) > 200:
        blocks = blocks[-200:]

    session = dict(session)
    session["reasoning_blocks"] = blocks
    return save_session(session)
