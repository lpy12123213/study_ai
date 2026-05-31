"""Essay evaluation API endpoints.

Two surfaces:

- ``POST /api/essay-evaluations/evaluate`` synchronous one-shot scoring (used
  by the frontend when the user wants the answer immediately, no long-task
  bookkeeping). Streams progress via JSON response when ``stream=true`` query
  parameter is passed.
- ``GET /api/essay-evaluations``, ``GET /api/essay-evaluations/{id}``,
  ``DELETE /api/essay-evaluations/{id}`` — history list / detail / delete.

The canonical long-task entry point lives at
``POST /api/tasks/essay-evaluations/evaluate`` (see ``backend.api.tasks``);
this module exposes the lightweight CRUD on top of the persisted records.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.database.repositories.generation.essay_evaluations import (
    delete_evaluation,
    get_evaluation,
    list_evaluations,
)
from backend.generation.essay_evaluation.essay_schemas import EssayEvaluationRequest, EssayEvaluationResult
from backend.generation.essay_evaluation.service import evaluate_essay
from backend.database.repositories.generation.essay_evaluations import insert_evaluation

router = APIRouter(prefix="/essay-evaluations", tags=["essay-evaluations"], dependencies=[Depends(require_auth)])
logger = get_logger(__name__)


def _require_user_id(user: dict) -> str:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return user_id


@router.post("/evaluate", response_model=Dict[str, Any])
async def evaluate(request: EssayEvaluationRequest, user: dict = Depends(require_auth)) -> Dict[str, Any]:
    """One-shot synchronous evaluation that also persists the result.

    Returns ``{"evaluation_id": int, "result": EssayEvaluationResult}``.
    Use ``POST /api/tasks/essay-evaluations/evaluate`` for streaming progress.
    """

    user_id = _require_user_id(user)

    try:
        result: EssayEvaluationResult = await evaluate_essay(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    feedback_payload: Dict[str, Any] = {
        "summary": result.summary,
        "strengths": list(result.strengths),
        "weaknesses": list(result.weaknesses),
        "suggestions": list(result.suggestions),
        "paragraph_feedback": [item.model_dump() for item in result.paragraph_feedback],
        "rewrite": result.rewrite,
    }

    record = await insert_evaluation(
        user_id=user_id,
        essay_text=request.text,
        subject=request.subject,
        topic=request.topic,
        essay_type=request.essay_type,
        grade_band=request.grade_band,
        language=result.language,
        requirements=request.requirements,
        score_total=result.score_total,
        score_max=result.score_max,
        grade=result.grade,
        scores=[s.model_dump() for s in result.scores],
        feedback=feedback_payload,
        model=result.model,
    )
    return {"evaluation_id": int(record.get("id") or 0), "result": result.model_dump()}


@router.get("", response_model=Dict[str, Any])
async def list_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10_000),
    user: dict = Depends(require_auth),
) -> Dict[str, Any]:
    user_id = _require_user_id(user)
    items: List[Dict[str, Any]] = await list_evaluations(user_id=user_id, limit=limit, offset=offset)
    return {"items": items, "count": len(items)}


@router.get("/{evaluation_id}", response_model=Dict[str, Any])
async def get_detail(evaluation_id: int, user: dict = Depends(require_auth)) -> Dict[str, Any]:
    user_id = _require_user_id(user)
    record = await get_evaluation(user_id=user_id, evaluation_id=evaluation_id)
    if not record:
        raise HTTPException(status_code=404, detail="evaluation_not_found")
    return record


@router.delete("/{evaluation_id}", response_model=Dict[str, Any])
async def delete(evaluation_id: int, user: dict = Depends(require_auth)) -> Dict[str, Any]:
    user_id = _require_user_id(user)
    ok = await delete_evaluation(user_id=user_id, evaluation_id=evaluation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="evaluation_not_found")
    return {"success": True}
