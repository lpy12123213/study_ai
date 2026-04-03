from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

HiddenFilter = Literal["0", "1", "all"]


class QuestionLibraryListResponseItem(BaseModel):
    question_id: str = ""
    subject: str = ""
    origin: str = ""
    hidden: bool = False
    ai_score: Optional[int] = None
    ai_verdict: str = ""
    ai_summary: str = ""
    updated_at: str = ""
    stem: str = ""


class QuestionLibraryListResponse(BaseModel):
    total: int = 0
    limit: int = 50
    offset: int = 0
    items: List[QuestionLibraryListResponseItem] = Field(default_factory=list)


class QuestionLibraryCrawlRequest(BaseModel):
    subject: str = ""
    edu_level: str = ""
    query: str = ""
    difficulty: str = ""
    question_type: str = ""
    limit: int = 30
    max_pages: int = 2
    min_quality_score: int = 0
    difficulty_value_min: Optional[float] = None
    difficulty_value_max: Optional[float] = None
    require_difficulty_value: bool = False
    task_id: str = ""


class QuestionLibraryCrawlResponse(BaseModel):
    success: bool = True
    inserted: int = 0
    subject: str = ""
    count: int = 0
    question_ids: List[str] = Field(default_factory=list)
    error: str = ""


class QuestionLibraryGenerateRequest(BaseModel):
    subject: str = ""
    topic: str = ""
    difficulty: str = ""
    question_type: str = ""
    count: int = 5
    use_study_archive: bool = True
    use_reference_questions: bool = True
    reference_source: Literal["any", "gaokao", "mock", "joint"] = "any"
    reference_year_range: Literal["all", "3", "5"] = "all"
    session_id: str = ""
    mode: Literal["standard", "infinite"] = "standard"
    grade_id: str = ""
    textbook_version_id: str = ""
    knowledge_point_ids: List[str] = Field(default_factory=list)
    knowledge_points: List[str] = Field(default_factory=list)
    append: bool = False
    stream_reasoning: bool = False
    task_id: str = ""


class QuestionLibraryDraftReviewDimension(BaseModel):
    name: str = ""
    score: int = 0
    comment: str = ""


class QuestionLibraryDraftReview(BaseModel):
    verdict: str = ""
    overall_score: int = 0
    dimensions: List[QuestionLibraryDraftReviewDimension] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    summary: str = ""
    model: str = ""

class QuestionLibraryDiagram(BaseModel):
    kind: str = ""
    url: str = ""
    filename: str = ""
    media_id: str = ""
    alt: str = ""
    caption: str = ""
    markdown: str = ""


class QuestionLibraryDraftQuestion(BaseModel):
    question_id: str = ""
    stem: str = ""
    answer: str = ""
    analysis: str = ""
    keep: bool = True
    review_status: Literal["pending_review", "in_review", "approved", "rejected", "confirmed", "committed"] = "pending_review"
    review: Optional[QuestionLibraryDraftReview] = None
    diagrams: Optional[List[QuestionLibraryDiagram]] = None


class QuestionLibraryPreviewData(BaseModel):
    preview_id: str = ""
    session_id: str = ""
    task_id: str = ""
    subject: str = ""
    topic: str = ""
    mode: Literal["standard", "infinite"] = "standard"
    use_reference_questions: bool = True
    reference_source: Literal["any", "gaokao", "mock", "joint"] = "any"
    reference_year_range: Literal["all", "3", "5"] = "all"
    count: int = 0
    draft_questions: List[QuestionLibraryDraftQuestion] = Field(default_factory=list)


class QuestionLibraryPreviewResponse(QuestionLibraryPreviewData):
    success: bool = True


class QuestionLibraryLatestPendingPreviewResponse(BaseModel):
    success: bool = True
    preview: Optional[QuestionLibraryPreviewData] = None


class QuestionLibraryCommitPreviewRequest(BaseModel):
    questions: List[QuestionLibraryDraftQuestion] = Field(default_factory=list)


class QuestionLibraryRegenerateSectionRequest(BaseModel):
    question_id: str = ""
    section_key: Literal["stem", "answer", "analysis"] = "analysis"


class QuestionLibraryCommitPreviewResponse(BaseModel):
    success: bool = True
    preview_id: str = ""
    inserted: int = 0
    subject: str = ""
    count: int = 0
    question_ids: List[str] = Field(default_factory=list)


class QuestionLibraryScoreRequest(BaseModel):
    subject: str = ""
    limit: int = 50
    only_unscored: bool = True
    task_id: str = ""


class QuestionLibraryBulkDeleteRequest(BaseModel):
    question_ids: List[str] = Field(default_factory=list)
