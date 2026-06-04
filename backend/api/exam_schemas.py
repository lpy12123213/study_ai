from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class StartExamRequest(BaseModel):
    paper_id: int = Field(..., gt=0)
    mode: str = Field(default="untimed")
    time_limit_minutes: Optional[int] = Field(default=None, ge=1, le=1440)

    @field_validator("mode")
    @classmethod
    def _mode(cls, value: str) -> str:
        raw = str(value or "").strip().lower()
        return "timed" if raw == "timed" else "untimed"


class SaveAnswerRequest(BaseModel):
    question_id: Optional[str] = None
    question_type: Optional[str] = None
    selected_options: List[str] = Field(default_factory=list)
    fill_blank_text: str = ""
    handwriting_image_path: str = ""
    text_answer: str = ""


class BatchSaveAnswersRequest(BaseModel):
    answers: List[SaveAnswerRequest] = Field(default_factory=list)


class ExamQuestion(BaseModel):
    question_id: str
    order: int = 0
    type: str = ""
    question_type: str = ""
    stem: str = ""
    difficulty: str = ""
    knowledge_point: str = ""
    source_url: str = ""
    max_score: float = 0.0
    student_answer: Optional[Dict[str, Any]] = None


class ExamSessionResponse(BaseModel):
    session_id: str
    paper_id: int
    paper_name: str
    mode: str
    time_limit_minutes: Optional[int] = None
    started_at: Optional[str] = None
    submitted_at: Optional[str] = None
    expires_at: Optional[str] = None
    status: str
    total_score: float = 0.0
    max_score: float = 0.0
    questions: List[ExamQuestion] = Field(default_factory=list)


class ExamResultResponse(BaseModel):
    session_id: str
    total_score: float
    max_score: float
    score_ratio: float
    objective_correct: int
    objective_total: int
    subjective_score: float
    subjective_max: float
    breakdown: List[Dict[str, Any]] = Field(default_factory=list)
    ai_feedback: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
