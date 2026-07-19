from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

HiddenFilter = Literal["0", "1", "all"]

PracticeGoal = Literal[
    "fluency",
    "structural_intuition",
    "intuition_correction",
    "transfer",
    "solution_appreciation",
]
IntuitionKind = Literal[
    "prediction",
    "representation",
    "invariant",
    "boundary",
    "counterexample",
    "solution_comparison",
]
FeedbackMode = Literal["guided", "concise", "reflective"]
IntuitionPacketStageName = Literal[
    "perception",
    "model_externalization",
    "minimal_check",
    "transfer",
    "appreciation",
]


class QuestionLibraryIntuitionPracticeConfig(BaseModel):
    practice_goal: PracticeGoal = "structural_intuition"
    intuition_kinds: List[IntuitionKind] = Field(
        default_factory=lambda: ["prediction", "representation", "invariant"]
    )
    packet_size: int = Field(default=3, ge=3, le=5)
    feedback_mode: FeedbackMode = "guided"


class QuestionLibraryIntuitionAtom(BaseModel):
    concept: str = ""
    internal_model: str = ""
    mental_action: str = ""
    decisive_cue: str = ""
    expected_first_feel: str = ""
    common_false_intuition: str = ""
    formal_anchor: str = ""
    transfer_mutation: str = ""
    boundary_flip: str = ""
    feedback: str = ""


class QuestionLibraryIntuitionPacketStage(BaseModel):
    stage: IntuitionPacketStageName
    kind: IntuitionKind
    prompt: str = ""
    hint: str = ""
    expected_answer: str = ""
    feedback: str = ""


class QuestionLibraryIntuitionCurriculumAlignment(BaseModel):
    knowledge_points: List[str] = Field(default_factory=list)
    scope_note: str = ""
    in_scope: Optional[bool] = None


class QuestionLibraryIntuitionValidation(BaseModel):
    status: Literal["pending", "passed", "failed"] = "pending"
    scope_ok: bool = False
    answer_correct: bool = False
    answer_analysis_consistent: bool = False
    conditions_sufficient: bool = False
    unambiguous: bool = False
    transfer_valid: bool = False
    issues: List[str] = Field(default_factory=list)
    repaired: bool = False


class QuestionLibraryIntuitionPacket(BaseModel):
    version: Literal["1.0"] = "1.0"
    practice_goal: PracticeGoal = "structural_intuition"
    atom: QuestionLibraryIntuitionAtom = Field(default_factory=QuestionLibraryIntuitionAtom)
    stages: List[QuestionLibraryIntuitionPacketStage] = Field(default_factory=list)
    curriculum_alignment: Optional[QuestionLibraryIntuitionCurriculumAlignment] = None
    validation: Optional[QuestionLibraryIntuitionValidation] = None


class QuestionLibraryPracticeStageStatePatch(BaseModel):
    initial_response: Optional[str] = None
    final_response: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=100)
    hint_level: Optional[int] = Field(default=None, ge=0, le=4)
    revealed_at_s: Optional[float] = Field(default=None, ge=0)


class QuestionLibraryPracticeStatePatch(BaseModel):
    phase: Optional[IntuitionPacketStageName] = None
    first_guess: Optional[str] = None
    final_response: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=100)
    hint_level: Optional[int] = Field(default=None, ge=0, le=4)
    transfer_correct: Optional[bool] = None
    reflection: Optional[str] = None
    stage_responses: Optional[Dict[IntuitionPacketStageName, QuestionLibraryPracticeStageStatePatch]] = None
    completed: Optional[bool] = None


class QuestionLibraryListResponseItem(BaseModel):
    question_id: str = ""
    subject: str = ""
    origin: str = ""
    hidden: bool = False
    ai_score: Optional[int] = None
    ai_verdict: str = ""
    ai_dimensions_json: str = ""
    ai_summary: str = ""
    thinking_depth_score: Optional[int] = None
    thinking_method_family: str = ""
    thinking_method_signature: str = ""
    thinking_method_rarity: str = ""
    thinking_method_count: Optional[int] = None
    thinking_depth_comment: str = ""
    updated_at: str = ""
    stem: str = ""


class QuestionLibraryListResponse(BaseModel):
    total: Optional[int] = 0
    include_total: bool = True
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
    intuition_practice: QuestionLibraryIntuitionPracticeConfig = Field(
        default_factory=QuestionLibraryIntuitionPracticeConfig
    )


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
    intuition_packet: Optional[QuestionLibraryIntuitionPacket] = None


class QuestionLibraryPreviewData(BaseModel):
    preview_id: str = ""
    session_id: str = ""
    task_id: str = ""
    subject: str = ""
    topic: str = ""
    mode: Literal["standard", "infinite"] = "standard"
    difficulty: str = ""
    question_type: str = ""
    use_study_archive: bool = True
    use_reference_questions: bool = True
    reference_source: Literal["any", "gaokao", "mock", "joint"] = "any"
    reference_year_range: Literal["all", "3", "5"] = "all"
    count: int = 0
    intuition_practice: QuestionLibraryIntuitionPracticeConfig = Field(
        default_factory=QuestionLibraryIntuitionPracticeConfig
    )
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
    batch_size: int = 50
    only_unscored: bool = True
    task_id: str = ""


class QuestionLibraryBulkDeleteRequest(BaseModel):
    question_ids: List[str] = Field(default_factory=list)
