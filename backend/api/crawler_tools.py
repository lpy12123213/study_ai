from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import require_auth
from backend.api.crawler_schemas import AvailableFiltersRequest, ComposeBlueprintRequest
from backend.config import DEFAULT_SUBJECT
from backend.crawler_manager import get_crawler
from backend.subjects import resolve_subject

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/available-filters")
async def available_filters(request: AvailableFiltersRequest) -> Dict[str, Any]:
    """Get available search filters for a subject (grades/textbook versions/question types/provinces, etc.)."""
    subject_input = (request.subject or DEFAULT_SUBJECT).strip()
    edu_level = (request.edu_level or "").strip()

    try:
        subject = resolve_subject(subject_input, edu_level=edu_level, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    crawler = await get_crawler(subject=subject, edu_level=edu_level, strict=True)
    result = await crawler.get_available_filters()
    result["applied_subject"] = subject
    if edu_level:
        result["applied_edu_level"] = edu_level
    return result


@router.post("/compose-blueprint")
async def compose_blueprint(request: ComposeBlueprintRequest) -> Dict[str, Any]:
    """Compose question IDs according to a multi-slot blueprint."""
    subject_input = (request.subject or DEFAULT_SUBJECT).strip()
    edu_level = (request.edu_level or "").strip()

    try:
        subject = resolve_subject(subject_input, edu_level=edu_level, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    crawler = await get_crawler(subject=subject, edu_level=edu_level, strict=True)
    result = await crawler.compose_paper_blueprint(
        blueprint=request.blueprint,
        subject=subject,
        edu_level=edu_level,
        learn_grade=request.learn_grade,
        learn_grade_id=request.learn_grade_id,
        textbook_version=request.textbook_version,
        elective_mode=request.elective_mode,
        elective_keywords=request.elective_keywords,
        exclude_elective=bool(request.exclude_elective),
        year=request.year,
        province=request.province,
        province_id=request.province_id,
        paper_type_id=request.paper_type_id,
        term=request.term,
        order_by=request.order_by,
        max_pages=request.max_pages,
        per_slot_expand=request.per_slot_expand,
        min_quality_score=request.min_quality_score,
        dedup_by_stem=bool(request.dedup_by_stem),
        strict_subject=bool(request.strict_subject),
        slot_concurrency=request.slot_concurrency,
        slot_delay_s=request.slot_delay_s,
        slot_retries=request.slot_retries,
    )
    result["applied_subject"] = subject
    if edu_level:
        result["applied_edu_level"] = edu_level
    return result

