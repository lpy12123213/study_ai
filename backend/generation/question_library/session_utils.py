from __future__ import annotations

import json
import time
from typing import Any, List

from backend.generation.question_library.intuition_practice import (
    PACKET_STAGES,
    normalize_intuition_packet,
    normalize_intuition_practice_config,
)

_REVIEW_STATUSES = {"pending_review", "in_review", "approved", "rejected", "confirmed", "committed"}


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _bounded_float(value: Any, *, minimum: float, maximum: float) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, parsed))


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, parsed))


def normalize_practice_stage_state(value: Any) -> dict:
    raw = value if isinstance(value, dict) else {}
    out: dict = {}
    for key in ("initial_response", "final_response"):
        if key in raw:
            out[key] = _bounded_text(raw.get(key), 5000)
    confidence = _bounded_float(raw.get("confidence"), minimum=0.0, maximum=100.0)
    if confidence is not None:
        out["confidence"] = confidence
    hint_level = _bounded_int(raw.get("hint_level"), minimum=0, maximum=4)
    if hint_level is not None:
        out["hint_level"] = hint_level
    revealed_at_s = _bounded_float(raw.get("revealed_at_s"), minimum=0.0, maximum=10_000_000_000.0)
    if revealed_at_s is not None:
        out["revealed_at_s"] = revealed_at_s
    return out


def normalize_practice_state(value: Any) -> dict:
    raw = value if isinstance(value, dict) else {}
    out: dict = {}
    phase = str(raw.get("phase") or "").strip()
    if phase in PACKET_STAGES:
        out["phase"] = phase
    for key, limit in (("first_guess", 4000), ("final_response", 6000), ("reflection", 4000)):
        if key in raw:
            out[key] = _bounded_text(raw.get(key), limit)
    confidence = _bounded_float(raw.get("confidence"), minimum=0.0, maximum=100.0)
    if confidence is not None:
        out["confidence"] = confidence
    hint_level = _bounded_int(raw.get("hint_level"), minimum=0, maximum=4)
    if hint_level is not None:
        out["hint_level"] = hint_level
    if "transfer_correct" in raw:
        out["transfer_correct"] = None if raw.get("transfer_correct") is None else bool(raw.get("transfer_correct"))
    stage_responses: dict[str, dict] = {}
    raw_stage_responses = raw.get("stage_responses") if isinstance(raw.get("stage_responses"), dict) else {}
    for stage, state in raw_stage_responses.items():
        stage_name = str(stage or "").strip()
        if stage_name not in PACKET_STAGES or not isinstance(state, dict):
            continue
        stage_responses[stage_name] = normalize_practice_stage_state(state)
    if stage_responses:
        out["stage_responses"] = stage_responses
    if "completed" in raw:
        out["completed"] = bool(raw.get("completed"))
    for key in ("updated_at_s", "completed_at_s"):
        timestamp = _bounded_float(raw.get(key), minimum=0.0, maximum=10_000_000_000.0)
        if timestamp is not None:
            out[key] = timestamp
    return out


def merge_practice_state(existing: Any, patch: Any, *, updated_at_s: float) -> dict:
    current = normalize_practice_state(existing)
    updates = patch if isinstance(patch, dict) else {}
    stage_patch = updates.get("stage_responses") if isinstance(updates.get("stage_responses"), dict) else {}
    for key in ("phase", "first_guess", "final_response", "confidence", "hint_level", "transfer_correct", "reflection"):
        if key in updates:
            current[key] = updates.get(key)

    merged_stages = dict(current.get("stage_responses") or {})
    for stage, value in stage_patch.items():
        stage_name = str(stage or "").strip()
        if stage_name not in PACKET_STAGES or not isinstance(value, dict):
            continue
        merged_stages[stage_name] = {
            **dict(merged_stages.get(stage_name) or {}),
            **dict(value),
        }
    if merged_stages:
        current["stage_responses"] = merged_stages

    if "completed" in updates:
        completed = bool(updates.get("completed"))
        current["completed"] = completed
        if completed:
            current["completed_at_s"] = float(updated_at_s)
        else:
            current.pop("completed_at_s", None)
    current["updated_at_s"] = float(updated_at_s)
    return normalize_practice_state(current)


def normalize_practice_attempts(value: Any) -> dict[str, dict]:
    raw = value if isinstance(value, dict) else {}
    out: dict[str, dict] = {}
    for question_id, state in raw.items():
        qid = _bounded_text(question_id, 80)
        if qid and isinstance(state, dict):
            out[qid] = normalize_practice_state(state)
    return out


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
        normalized = {
                "question_id": qid,
                "stem": str(item.get("stem") or "").strip(),
                "answer": str(item.get("answer") or "").strip(),
                "analysis": str(item.get("analysis") or "").strip(),
                "keep": bool(item.get("keep", True)),
                "review_status": normalize_review_status(item.get("review_status")),
                "review": dict(review) if review else None,
                **({"diagrams": normalized_diagrams} if normalized_diagrams is not None else {}),
            }
        intuition_packet = item.get("intuition_packet")
        if isinstance(intuition_packet, dict):
            normalized["intuition_packet"] = normalize_intuition_packet(
                intuition_packet,
                practice_config=intuition_packet,
                atom=intuition_packet.get("atom") if isinstance(intuition_packet.get("atom"), dict) else {},
                legacy_question=normalized,
            )
        out.append(normalized)
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
        "intuition_practice": normalize_intuition_practice_config((obj or {}).get("intuition_practice")),
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
        "intuition_practice": normalize_intuition_practice_config((session or {}).get("intuition_practice")),
        "count": len(drafts),
        "task_ids": list(session.get("task_ids") or []) if isinstance(session.get("task_ids"), list) else [],
        "latest_task_id": str((session or {}).get("latest_task_id") or "").strip(),
        "updated_at_s": float((session or {}).get("updated_at_s") or (session or {}).get("created_at_s") or 0.0),
        "created_at_s": float((session or {}).get("created_at_s") or 0.0),
        "reasoning_blocks_count": len(reasoning_blocks),
        "practice_attempts_count": len(normalize_practice_attempts((session or {}).get("practice_attempts"))),
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
