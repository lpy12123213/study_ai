
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.generation.question_library.generation import build_ai_question_id
from backend.generation.question_library.intuition_practice import normalize_intuition_practice_config
from backend.generation.question_library.preview_store import load_session, new_preview_id, new_session_id, save_session
from backend.generation.question_library.session_utils import (
    draft_identity,
    normalize_draft_questions,
    normalize_review_status,
)
from backend.shared.numparse import clamp_float_optional as _clamp_float  # noqa: F401  # re-export for runner.py
from backend.shared.numparse import clamp_int as _clamp_int  # noqa: F401  # re-export for runner.py
from backend.shared.tasks import RuntimeTask, task_runtime


def _utcnow() -> datetime:
    return datetime.now(UTC)



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
    use_reference_questions: bool,
    reference_source: str,
    reference_year_range: str,
    grade_id: str,
    textbook_version_id: str,
    knowledge_point_ids: List[str],
    knowledge_points: List[str],
    task_id: str,
    stream_reasoning: bool,
    intuition_practice: Optional[dict] = None,
) -> dict:
    existing = load_session(session_id) if session_id else None
    session = dict(existing or {})
    sid = str(session_id or session.get("session_id") or "").strip() or new_session_id()
    pid = str(preview_id or session.get("preview_id") or "").strip()
    if not pid:
        pid = new_preview_id()

    preview_ids = list(session.get("preview_ids") or []) if isinstance(session.get("preview_ids"), list) else []
    if pid and pid not in preview_ids:
        preview_ids.append(pid)
    session["preview_id"] = pid
    session["preview_ids"] = preview_ids

    session["session_id"] = sid
    session["user_id"] = str(user_id or "").strip()
    session["status"] = str(session.get("status") or "pending_review").strip() or "pending_review"
    session["mode"] = str(mode or session.get("mode") or "standard").strip() or "standard"
    session["subject"] = subject
    session["topic"] = topic
    session["difficulty"] = difficulty
    session["question_type"] = question_type
    requested_count = max(0, int(count or 0))
    draft_count = len(normalize_draft_questions(session.get("draft_questions")))
    session["requested_count"] = requested_count
    session["draft_count"] = draft_count
    # ``count`` remains the backwards-compatible visible draft total.  The
    # amount requested for the current batch lives in ``requested_count``.
    session["count"] = draft_count
    session["use_study_archive"] = bool(use_study_archive)
    session["use_reference_questions"] = bool(use_reference_questions)
    session["reference_source"] = str(reference_source or "any").strip() or "any"
    session["reference_year_range"] = str(reference_year_range or "all").strip() or "all"
    session["grade_id"] = str(grade_id or "").strip()
    session["textbook_version_id"] = str(textbook_version_id or "").strip()
    session["knowledge_point_ids"] = [str(item or "").strip() for item in (knowledge_point_ids or []) if str(item or "").strip()]
    session["knowledge_points"] = [str(item or "").strip() for item in (knowledge_points or []) if str(item or "").strip()]
    session["stream_reasoning"] = bool(stream_reasoning)
    session["intuition_practice"] = normalize_intuition_practice_config(
        intuition_practice or session.get("intuition_practice")
    )
    session["stop_requested"] = False if task_id else bool(session.get("stop_requested"))

    task_ids = list(session.get("task_ids") or []) if isinstance(session.get("task_ids"), list) else []
    if task_id and task_id not in task_ids:
        task_ids.append(task_id)
    session["task_ids"] = task_ids
    session["latest_task_id"] = task_ids[-1] if task_ids else ""

    session.setdefault("reasoning_blocks", [])
    session.setdefault("draft_questions", [])
    session.setdefault("confirmed_question_ids", [])
    session.setdefault("practice_attempts", {})
    return save_session(session)


def normalize_topic_key(topic: str) -> str:
    raw = str(topic or "").strip()
    if not raw:
        return ""

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
    return first_line[:120].strip()


def infer_question_type_from_topic(topic: str) -> str:
    raw = str(topic or "")
    if "选择题" in raw and "解答题" in raw:
        return "选择题+解答题"
    for hint in ("选择题", "解答题", "填空题", "判断题", "证明题", "综合题", "问答题"):
        if hint in raw:
            return hint
    return ""


class RunnerError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = str(detail or "runner_error")
        self.status_code = int(status_code or 400)





def _now_iso_z() -> str:
    return _utcnow().isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _emit_event(
    task: RuntimeTask,
    *,
    event_type: str,
    data: Dict[str, Any],
    user_id: str = "",
    persist_task_id: str = "",
    progress: Optional[float] = None,
) -> None:
    _ = user_id, persist_task_id, progress
    await task_runtime.append_event(task, {"type": str(event_type or "").strip() or "event", "data": dict(data or {})})


def _merge_reasoning_block(session: dict, *, task_id: str, payload: dict) -> dict:
    if not isinstance(session, dict):
        return session

    stage_id = str(payload.get("stage_id") or "").strip() or "default"
    stage_label = str(payload.get("stage_label") or "").strip() or stage_id
    source = str(payload.get("source") or "").strip() or "trace"
    content = str(payload.get("content") or "").strip()
    if not content:
        return session

    blocks = list(session.get("reasoning_blocks") or []) if isinstance(session.get("reasoning_blocks"), list) else []
    if (
        blocks
        and isinstance(blocks[-1], dict)
        and str(blocks[-1].get("task_id") or "").strip() == str(task_id or "").strip()
        and str(blocks[-1].get("stage_id") or "").strip() == stage_id
        and str(blocks[-1].get("source") or "").strip() == source
    ):
        blocks[-1]["content"] = str(blocks[-1].get("content") or "").rstrip() + content
    else:
        blocks.append(
            {
                "id": f"reason-{uuid.uuid4().hex[:12]}",
                "task_id": str(task_id or "").strip(),
                "stage_id": stage_id,
                "stage_label": stage_label,
                "source": source,
                "content": content,
                "created_at": _now_iso_z(),
            }
        )

    session = dict(session)
    session["reasoning_blocks"] = blocks[-200:]
    return session


def _append_reasoning_status(session: dict, *, task_id: str, payload: dict) -> dict:
    if not isinstance(session, dict):
        return session

    stage_id = str(payload.get("stage_id") or "").strip() or "default"
    stage_label = str(payload.get("stage_label") or "").strip() or stage_id
    mode = str(payload.get("mode") or "").strip() or "trace"
    message = str(payload.get("message") or "").strip()
    if not message:
        return session

    statuses = (
        list(session.get("reasoning_statuses") or []) if isinstance(session.get("reasoning_statuses"), list) else []
    )
    statuses.append(
        {
            "task_id": str(task_id or "").strip(),
            "stage_id": stage_id,
            "stage_label": stage_label,
            "mode": mode,
            "message": message,
            "created_at": _now_iso_z(),
        }
    )

    session = dict(session)
    session["reasoning_statuses"] = statuses[-200:]
    return session


def _materialize_drafts(
    drafts: List[dict],
    *,
    existing_drafts: List[dict],
    draft_key_to_id: Dict[str, str],
) -> Tuple[List[dict], Dict[str, str]]:
    for item in normalize_draft_questions(existing_drafts):
        key = draft_identity(item)
        qid = str(item.get("question_id") or "").strip()
        if key and qid:
            draft_key_to_id.setdefault(key, qid)

    out: List[dict] = []
    for item in drafts or []:
        if not isinstance(item, dict):
            continue
        stem = str(item.get("stem") or "").strip()
        answer = str(item.get("answer") or "").strip()
        analysis = str(item.get("analysis") or "").strip()
        if not stem or not answer or not analysis:
            continue
        diagrams = item.get("diagrams")
        normalized_diagrams = [d for d in diagrams if isinstance(d, dict)][:6] if isinstance(diagrams, list) else None
        intuition_packet = item.get("intuition_packet") if isinstance(item.get("intuition_packet"), dict) else None
        key = draft_identity({"stem": stem, "answer": answer, "analysis": analysis})
        qid = str(item.get("question_id") or "").strip() or draft_key_to_id.get(key) or build_ai_question_id(
            suffix=uuid.uuid4().hex[:8]
        )
        draft_key_to_id[key] = qid
        out.append(
            {
                "question_id": qid,
                "stem": stem,
                "answer": answer,
                "analysis": analysis,
                "keep": bool(item.get("keep", True)),
                "review_status": normalize_review_status(item.get("review_status")),
                "review": dict(item.get("review") or {}) if isinstance(item.get("review"), dict) else None,
                **(
                    {"consistency_score": float(item.get("consistency_score"))}
                    if item.get("consistency_score") is not None
                    else {}
                ),
                **({"diagrams": normalized_diagrams} if normalized_diagrams is not None else {}),
                **({"intuition_packet": dict(intuition_packet)} if intuition_packet is not None else {}),
            }
        )
    return out, draft_key_to_id
