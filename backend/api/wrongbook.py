from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.core.srs import RATING_QUALITY
from backend.database.repositories.content.wrongbook import aggregate_mastery_by_knowledge_point as db_aggregate_mastery
from backend.database.repositories.content.wrongbook import count_due_reviews as db_count_due_reviews
from backend.database.repositories.content.wrongbook import delete_wrong_question as db_delete_wrong_question
from backend.database.repositories.content.wrongbook import list_due_reviews as db_list_due_reviews
from backend.database.repositories.content.wrongbook import list_wrong_questions as db_list_wrong_questions
from backend.database.repositories.content.wrongbook import record_review as db_record_review
from backend.database.repositories.content.wrongbook import upsert_wrong_question as db_upsert_wrong_question
from backend.database.repositories.question.papers import save_paper as db_save_paper

router = APIRouter(prefix="/wrongbook", tags=["wrongbook"], dependencies=[Depends(require_auth)])
logger = get_logger(__name__)


@router.get("", response_model=dict)
async def list_wrongbook(
    subject: Optional[str] = Query(None),
    knowledge_point: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=200),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    items = await db_list_wrong_questions(
        user_id=user_id,
        subject=subject,
        knowledge_point=knowledge_point,
        q=q,
        limit=limit,
    )
    return {"items": items, "count": len(items)}


@router.post("", response_model=dict)
async def upsert_wrongbook_item(payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    question_id = str(payload.get("question_id") or payload.get("questionId") or "").strip()
    subject = str(payload.get("subject") or "").strip()
    knowledge_point = str(payload.get("knowledge_point") or payload.get("knowledgePoint") or "").strip()
    mastery = payload.get("mastery")
    note = str(payload.get("note") or "").strip()
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else None
    source_ref = payload.get("source_ref") if isinstance(payload.get("source_ref"), dict) else None

    try:
        out = await db_upsert_wrong_question(
            user_id=user_id,
            question_id=question_id,
            subject=subject,
            knowledge_point=knowledge_point,
            mastery=mastery if mastery is None else int(mastery),
            note=note,
            tags=tags,
            source_ref=source_ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("upsert_wrong_question_failed", extra={"user_id": user_id, "question_id": question_id})
        raise HTTPException(status_code=500, detail="upsert_wrong_question_failed")

    return {"success": True, "item": out}


@router.get("/review/queue", response_model=dict)
async def get_review_queue(
    subject: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    items = await db_list_due_reviews(user_id=user_id, subject=subject, limit=limit)
    due_count = await db_count_due_reviews(user_id=user_id, subject=subject)
    return {"items": items, "due_count": due_count, "total": due_count}


@router.post("/review/{question_id}", response_model=dict)
async def record_wrongbook_review(question_id: str, payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    rating = str(payload.get("rating") or "").strip()
    if rating not in RATING_QUALITY:
        raise HTTPException(status_code=400, detail="invalid_review_rating")
    try:
        item = await db_record_review(user_id=user_id, question_id=str(question_id or "").strip(), rating=rating)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("wrongbook_review_failed", extra={"user_id": user_id, "question_id": question_id})
        raise HTTPException(status_code=500, detail="wrongbook_review_failed")
    if item is None:
        raise HTTPException(status_code=404, detail="wrong_question_not_found")
    return {"success": True, "item": item, "next_review_at": item.get("next_review_at") or ""}


@router.get("/mastery", response_model=dict)
async def get_wrongbook_mastery(subject: Optional[str] = Query(None), user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return await db_aggregate_mastery(user_id=user_id, subject=subject)


@router.delete("/{question_id}", response_model=dict)
async def delete_wrongbook_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await db_delete_wrong_question(user_id=user_id, question_id=str(question_id or "").strip())
    if not ok:
        raise HTTPException(status_code=404, detail="wrong_question_not_found")
    return {"success": True}


@router.post("/practice", response_model=dict)
async def generate_practice_paper(payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    """Create a practice paper from wrongbook questions (filtered by knowledge point / selection)."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    paper_name = str(payload.get("paper_name") or payload.get("paperName") or "错题练习卷").strip() or "错题练习卷"
    question_ids = payload.get("question_ids") if isinstance(payload.get("question_ids"), list) else payload.get("questionIds")
    selected = [str(x or "").strip() for x in (question_ids or []) if str(x or "").strip()]
    knowledge_point = str(payload.get("knowledge_point") or payload.get("knowledgePoint") or "").strip()

    items = await db_list_wrong_questions(user_id=user_id, knowledge_point=knowledge_point or None, limit=200)
    if selected:
        wanted = set(selected)
        items = [x for x in items if str(x.get("question_id") or "") in wanted]

    if not items:
        raise HTTPException(status_code=400, detail="no_wrong_questions_selected")

    questions: List[dict] = []
    for idx, it in enumerate(items, start=1):
        questions.append(
            {
                "question_id": str(it.get("question_id") or ""),
                "question_order": idx,
                "knowledge_point": str(it.get("knowledge_point") or ""),
                "difficulty": "",
                "question_type": "错题",
                "source_url": "",
            }
        )

    try:
        paper_id = await db_save_paper(user_id=user_id, paper_name=paper_name[:200], questions=questions)
    except Exception:
        logger.exception("wrongbook_practice_paper_create_failed", extra={"user_id": user_id})
        raise HTTPException(status_code=500, detail="practice_paper_create_failed")

    return {"success": True, "paper_id": paper_id}
