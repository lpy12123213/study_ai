"""OpenAI Function Calling adapter routes.

The canonical FastAPI app includes this router through the integrations domain.
`backend.core.openai_adapter` remains only as a standalone compatibility entrypoint.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.crawler_schemas import AvailableFiltersRequest, ComposeBlueprintRequest
from backend.core.logging_utils import get_logger
from backend.core.settings import DEFAULT_SUBJECT
from backend.core.subjects import DEFAULT_DIFFICULTY, normalize_difficulty, resolve_subject
from backend.integrations.crawler.interface import CrawlerInterface
from backend.integrations.crawler.manager import get_crawler as get_subject_crawler
from backend.database.repositories.question.papers import get_paper, list_papers, save_paper

logger = get_logger(__name__)
router = APIRouter(tags=["openai-adapter"])


async def get_crawler(subject: str = "", edu_level: str = "") -> CrawlerInterface:
    """Get or create a crawler instance for the requested subject."""
    subject_value = (subject or DEFAULT_SUBJECT).strip()
    edu_level_value = (edu_level or "").strip()
    return await get_subject_crawler(subject=subject_value, edu_level=edu_level_value, strict=True)


class SearchByKeywordRequest(BaseModel):
    keyword: str
    subject: str = ""
    edu_level: str = ""
    learn_grade: str = ""
    learn_grade_id: int = 0
    textbook_version: str = ""
    limit: int = 20
    difficulty: str = ""
    question_type: str = ""
    max_pages: int = 3
    year: int = 0
    source_contains: str = ""
    stem_contains: str = ""
    knowledge_contains: str = ""
    elective_mode: str = ""
    elective_keywords: Optional[List[str]] = None
    exclude_elective: bool = False
    dedup_by_stem: bool = False
    min_quality_score: int = 0
    with_quality: bool = True
    difficulty_value_min: Optional[float] = None
    difficulty_value_max: Optional[float] = None
    province: str = ""
    province_id: int = -1
    paper_type_id: int = 0
    term: int = 0
    order_by: int = 2


class SearchByKnowledgeRequest(BaseModel):
    knowledge_point: str
    subject: str
    edu_level: str = ""
    learn_grade: str = ""
    learn_grade_id: int = 0
    textbook_version: str = ""
    limit: int = 20
    difficulty: str = ""
    question_type: str = ""
    max_pages: int = 3
    year: int = 0
    source_contains: str = ""
    stem_contains: str = ""
    knowledge_contains: str = ""
    elective_mode: str = ""
    elective_keywords: Optional[List[str]] = None
    exclude_elective: bool = False
    dedup_by_stem: bool = False
    min_quality_score: int = 0
    with_quality: bool = True
    difficulty_value_min: Optional[float] = None
    difficulty_value_max: Optional[float] = None
    province: str = ""
    province_id: int = -1
    paper_type_id: int = 0
    term: int = 0
    order_by: int = 2


class FilterQuestionsRequest(BaseModel):
    question_ids: List[str]
    difficulty: str = ""
    question_type: str = ""
    limit: int = 10


class CreatePaperRequest(BaseModel):
    paper_name: str
    question_ids: List[str]


@router.post("/search-by-keyword")
async def search_by_keyword(request: SearchByKeywordRequest) -> Dict[str, Any]:
    """Search questions by keyword for OpenAI Function Calling clients."""
    subject = request.subject or DEFAULT_SUBJECT
    try:
        subject = resolve_subject(subject, edu_level=request.edu_level, strict=True)
        difficulty = normalize_difficulty(request.difficulty or DEFAULT_DIFFICULTY, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    crawler_instance = await get_crawler(subject, edu_level=request.edu_level)
    result = await crawler_instance.search_by_keyword(
        keyword=request.keyword,
        subject=subject,
        edu_level=request.edu_level,
        learn_grade=request.learn_grade,
        learn_grade_id=request.learn_grade_id,
        textbook_version=request.textbook_version,
        limit=request.limit,
        difficulty=difficulty,
        question_type=request.question_type,
        max_pages=request.max_pages,
        year=request.year,
        province=request.province,
        province_id=request.province_id,
        paper_type_id=request.paper_type_id,
        term=request.term,
        order_by=request.order_by,
        source_contains=request.source_contains,
        stem_contains=request.stem_contains,
        knowledge_contains=request.knowledge_contains,
        elective_mode=request.elective_mode,
        elective_keywords=request.elective_keywords,
        exclude_elective=bool(request.exclude_elective),
        dedup_by_stem=bool(request.dedup_by_stem),
        min_quality_score=request.min_quality_score,
        with_quality=bool(request.with_quality),
        difficulty_value_min=request.difficulty_value_min,
        difficulty_value_max=request.difficulty_value_max,
        require_difficulty=True,
        strict_subject=True,
    )
    result["applied_subject"] = subject
    result["applied_difficulty"] = difficulty
    return result


@router.post("/search-by-knowledge")
async def search_by_knowledge(request: SearchByKnowledgeRequest) -> Dict[str, Any]:
    """Search questions by knowledge point for OpenAI Function Calling clients."""
    try:
        subject = resolve_subject(request.subject, edu_level=request.edu_level, strict=True)
        difficulty = normalize_difficulty(request.difficulty or DEFAULT_DIFFICULTY, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    crawler_instance = await get_crawler(subject, edu_level=request.edu_level)
    result = await crawler_instance.search_by_knowledge(
        knowledge_point=request.knowledge_point,
        subject=subject,
        edu_level=request.edu_level,
        learn_grade=request.learn_grade,
        learn_grade_id=request.learn_grade_id,
        textbook_version=request.textbook_version,
        limit=request.limit,
        difficulty=difficulty,
        question_type=request.question_type,
        max_pages=request.max_pages,
        year=request.year,
        province=request.province,
        province_id=request.province_id,
        paper_type_id=request.paper_type_id,
        term=request.term,
        order_by=request.order_by,
        source_contains=request.source_contains,
        stem_contains=request.stem_contains,
        knowledge_contains=request.knowledge_contains,
        elective_mode=request.elective_mode,
        elective_keywords=request.elective_keywords,
        exclude_elective=bool(request.exclude_elective),
        dedup_by_stem=bool(request.dedup_by_stem),
        min_quality_score=request.min_quality_score,
        with_quality=bool(request.with_quality),
        difficulty_value_min=request.difficulty_value_min,
        difficulty_value_max=request.difficulty_value_max,
        require_difficulty=True,
        strict_subject=True,
    )
    result["applied_subject"] = subject
    result["applied_difficulty"] = difficulty
    return result


@router.post("/filter-questions")
async def filter_questions(request: FilterQuestionsRequest) -> Dict[str, Any]:
    """Filter questions for OpenAI Function Calling clients."""
    crawler_instance = await get_crawler()
    return await crawler_instance.filter_questions(
        question_ids=request.question_ids,
        difficulty=request.difficulty,
        question_type=request.question_type,
        limit=request.limit,
    )


@router.get("/question-info/{question_id}")
async def get_question_info(question_id: str) -> Dict[str, Any]:
    """Get question details for OpenAI Function Calling clients."""
    crawler_instance = await get_crawler()
    return await crawler_instance.get_question_info(question_id)


@router.post("/create-paper")
async def create_paper(request: CreatePaperRequest) -> Dict[str, Any]:
    """Create a paper from question IDs."""
    try:
        questions = [{"question_id": qid} for qid in request.question_ids]
        paper_id = await save_paper(user_id="1", paper_name=request.paper_name, questions=questions)
        return {"success": True, "paper_id": paper_id, "message": f"试卷 '{request.paper_name}' 创建成功"}
    except Exception as exc:
        logger.exception("openai_adapter_create_paper_failed")
        raise HTTPException(status_code=500, detail="create_paper_failed") from exc


@router.post("/available-filters")
async def available_filters(request: AvailableFiltersRequest) -> Dict[str, Any]:
    """Get available filters for the current subject."""
    subject = request.subject or DEFAULT_SUBJECT
    try:
        subject = resolve_subject(subject, edu_level=request.edu_level, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    crawler_instance = await get_crawler(subject, edu_level=request.edu_level)
    result = await crawler_instance.get_available_filters()
    result["applied_subject"] = subject
    if request.edu_level:
        result["applied_edu_level"] = request.edu_level
    return result


@router.post("/compose-blueprint")
async def compose_blueprint(request: ComposeBlueprintRequest) -> Dict[str, Any]:
    """Search and assemble question IDs from a blueprint."""
    subject = request.subject or DEFAULT_SUBJECT
    try:
        subject = resolve_subject(subject, edu_level=request.edu_level, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    crawler_instance = await get_crawler(subject, edu_level=request.edu_level)
    result = await crawler_instance.compose_paper_blueprint(
        blueprint=request.blueprint,
        subject=subject,
        edu_level=request.edu_level,
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
    if request.edu_level:
        result["applied_edu_level"] = request.edu_level
    return result


@router.get("/papers")
async def get_papers(limit: int = 50) -> List[dict]:
    """List papers for the adapter compatibility user."""
    return await list_papers(user_id="1", limit=limit)


@router.get("/papers/{paper_id}")
async def get_paper_detail(paper_id: int) -> dict:
    """Get paper details for the adapter compatibility user."""
    paper = await get_paper(user_id="1", paper_id=paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")
    return paper

