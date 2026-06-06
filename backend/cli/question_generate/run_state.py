"""Session bootstrap helpers for the question-generation runner."""

from __future__ import annotations

from typing import Dict, List, Tuple

from backend.generation.question_library.preview_store import save_session

from .args import RunParams
from .live_ui import _UiState
from .session import (
    _draft_identity,
    _ensure_session,
    _normalize_draft_questions,
    _save_preview_for_session,
)


def _prepare_generation_state(params: RunParams) -> Tuple[dict, _UiState, List[dict], Dict[str, str]]:
    session = _ensure_session(
        session_id=params.session_id,
        user_id=params.user_id,
        preview_id=params.preview_id,
        subject=params.subject,
        topic=params.topic,
        difficulty=params.difficulty,
        question_type=params.question_type,
        mode=params.mode,
        count=params.count,
        use_reference_questions=params.use_reference_questions,
        reference_source=params.reference_source,
        reference_year_range=params.reference_year_range,
        stream_reasoning=params.stream_reasoning,
        use_mcp_search=params.use_mcp_search,
        mcp_search_provider=params.mcp_search_provider,
        mcp_search_mode=params.mcp_search_mode,
        mcp_search_recency_days=params.mcp_search_recency_days,
        mcp_search_limit=params.mcp_search_limit,
        mcp_search_query=params.mcp_search_query,
    )
    session["status"] = "running"
    session = save_session(session)
    _save_preview_for_session(session, preview_status="running")

    progress_drafts = _normalize_draft_questions(session.get("draft_questions"))
    ui_state = _UiState(session_id=params.session_id)
    ui_state.batch_index = 0
    ui_state.draft_count = len(progress_drafts)

    draft_key_to_id: Dict[str, str] = {}
    for draft in progress_drafts:
        qid = str((draft or {}).get("question_id") or "").strip()
        key = _draft_identity(draft)
        if qid and key:
            draft_key_to_id[key] = qid

    return session, ui_state, progress_drafts, draft_key_to_id
