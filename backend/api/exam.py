from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from backend.api.auth import require_auth
from backend.api.exam_schemas import (
    BatchSaveAnswersRequest,
    ExamResultResponse,
    ExamSessionResponse,
    SaveAnswerRequest,
    StartExamRequest,
)
from backend.core.logging_utils import get_logger
from backend.database.repositories.exam import exam_sessions as exam_repo
from backend.generation.exam_grading.orchestrator import grade_exam_session

router = APIRouter(dependencies=[Depends(require_auth)])
logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HANDWRITING_DIR = PROJECT_ROOT / ".local" / "media" / "exam_handwriting"
ALLOWED_HANDWRITING_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_HANDWRITING_BYTES = 10 * 1024 * 1024


def _user_id(user: dict) -> str:
    uid = str((user or {}).get("user_id") or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return uid


def _not_found() -> None:
    raise HTTPException(status_code=404, detail="exam_session_not_found")


def _answer_payload(payload: SaveAnswerRequest, *, question_id: Optional[str] = None) -> dict:
    return {
        "question_id": str(question_id or payload.question_id or "").strip(),
        "question_type": str(payload.question_type or "").strip(),
        "selected_options": list(payload.selected_options or []),
        "fill_blank_text": payload.fill_blank_text,
        "handwriting_image_path": payload.handwriting_image_path,
        "text_answer": payload.text_answer,
    }


@router.post("/exam/sessions", response_model=ExamSessionResponse)
async def start_exam(payload: StartExamRequest, user: dict = Depends(require_auth)) -> dict:
    try:
        return await exam_repo.create_exam_session(
            user_id=_user_id(user),
            paper_id=payload.paper_id,
            mode=payload.mode,
            time_limit_minutes=payload.time_limit_minutes,
        )
    except ValueError as exc:
        if str(exc) == "paper_not_found":
            raise HTTPException(status_code=404, detail="paper_not_found") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/exam/sessions", response_model=list[dict])
async def list_exam_sessions(
    paper_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_auth),
) -> list[dict]:
    return await exam_repo.list_user_sessions(user_id=_user_id(user), paper_id=paper_id, limit=limit)


@router.get("/exam/sessions/{session_id}", response_model=ExamSessionResponse)
async def get_exam_session(
    session_id: str,
    include_answers: bool = Query(False),
    user: dict = Depends(require_auth),
) -> dict:
    session = await exam_repo.get_exam_session(
        user_id=_user_id(user),
        session_id=session_id,
        include_answers=include_answers,
    )
    if not session:
        _not_found()
    return session


@router.put("/exam/sessions/{session_id}/answers/{question_id}", response_model=dict)
async def save_exam_answer(
    session_id: str,
    question_id: str,
    payload: SaveAnswerRequest,
    user: dict = Depends(require_auth),
) -> dict:
    try:
        answer = await exam_repo.save_answer(
            user_id=_user_id(user),
            session_id=session_id,
            question_id=question_id,
            answer_data=_answer_payload(payload, question_id=question_id),
        )
    except ValueError as exc:
        detail = str(exc)
        if detail in {"session_not_found", "question_not_found"}:
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return {"success": True, "answer": answer}


@router.put("/exam/sessions/{session_id}/answers/batch", response_model=dict)
async def batch_save_exam_answers(
    session_id: str,
    payload: BatchSaveAnswersRequest,
    user: dict = Depends(require_auth),
) -> dict:
    try:
        answers = await exam_repo.batch_save_answers(
            user_id=_user_id(user),
            session_id=session_id,
            answers=[_answer_payload(answer) for answer in payload.answers],
        )
    except ValueError as exc:
        detail = str(exc)
        if detail in {"session_not_found", "question_not_found"}:
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return {"success": True, "answers": answers}


@router.post("/exam/sessions/{session_id}/answers/{question_id}/handwriting", response_model=dict)
async def upload_handwriting_answer(
    session_id: str,
    question_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(require_auth),
) -> dict:
    uid = _user_id(user)
    session = await exam_repo.get_exam_session(user_id=uid, session_id=session_id)
    if not session:
        _not_found()

    content_type = str(file.content_type or "").split(";")[0].strip().lower()
    suffix = ALLOWED_HANDWRITING_TYPES.get(content_type)
    if not suffix:
        guessed = mimetypes.guess_extension(content_type or "")
        if guessed not in set(ALLOWED_HANDWRITING_TYPES.values()):
            raise HTTPException(status_code=415, detail="unsupported_media_type")
        suffix = guessed

    data = await file.read(MAX_HANDWRITING_BYTES + 1)
    if len(data) > MAX_HANDWRITING_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    if not data:
        raise HTTPException(status_code=400, detail="empty_file")

    safe_uid = "".join(ch for ch in uid if ch.isalnum() or ch in {"-", "_"})[:80] or "user"
    safe_session = "".join(ch for ch in session_id if ch.isalnum() or ch in {"-", "_"})[:80]
    safe_qid = "".join(ch for ch in question_id if ch.isalnum() or ch in {"-", "_"})[:80] or "question"
    target_dir = HANDWRITING_DIR / safe_uid / safe_session
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_qid}_{int(time.time() * 1000)}{suffix}"
    path = (target_dir / filename).resolve()
    try:
        path.relative_to(HANDWRITING_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_path")
    path.write_bytes(data)

    rel_path = f"{safe_uid}/{safe_session}/{filename}"
    url = f"/api/media/exam-handwriting/{safe_session}/{filename}"
    await exam_repo.save_answer(
        user_id=uid,
        session_id=session_id,
        question_id=question_id,
        answer_data={"handwriting_image_path": rel_path},
    )
    return {"success": True, "url": url, "path": rel_path}


@router.post("/exam/sessions/{session_id}/submit", response_model=ExamResultResponse)
async def submit_exam(session_id: str, user: dict = Depends(require_auth)) -> dict:
    try:
        return await grade_exam_session(user_id=_user_id(user), session_id=session_id)
    except ValueError as exc:
        if str(exc) == "session_not_found":
            _not_found()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/exam/sessions/{session_id}/result", response_model=ExamResultResponse)
async def get_exam_result(session_id: str, user: dict = Depends(require_auth)) -> dict:
    result = await exam_repo.get_exam_result(user_id=_user_id(user), session_id=session_id)
    if not result:
        raise HTTPException(status_code=404, detail="exam_result_not_found")
    return result


@router.get("/media/exam-handwriting/{session_id}/{filename}")
async def get_handwriting_media(session_id: str, filename: str, user: dict = Depends(require_auth)) -> FileResponse:
    uid = _user_id(user)
    session = await exam_repo.get_exam_session(user_id=uid, session_id=session_id, include_answers=True)
    if not session:
        _not_found()
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid_filename")

    safe_uid = "".join(ch for ch in uid if ch.isalnum() or ch in {"-", "_"})[:80] or "user"
    safe_session = "".join(ch for ch in session_id if ch.isalnum() or ch in {"-", "_"})[:80]
    path = (HANDWRITING_DIR / safe_uid / safe_session / filename).resolve()
    try:
        path.relative_to(HANDWRITING_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_path")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="not_found")
    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})
