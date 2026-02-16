from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class QuestionItem(BaseModel):
    question_id: str
    type: Optional[str] = ""
    difficulty: Optional[str] = ""
    knowledge_point: Optional[str] = ""
    source_url: Optional[str] = ""


class PaperCreate(BaseModel):
    paper_name: str
    questions: Optional[List[QuestionItem]] = None
    question_ids: Optional[List[str]] = None

    @model_validator(mode="after")
    def _validate_questions(self) -> "PaperCreate":
        if not self.questions and not self.question_ids:
            raise ValueError("questions_or_question_ids_required")
        return self

    def to_question_dicts(self) -> List[dict]:
        if self.questions:
            return [q.model_dump() for q in self.questions]
        return [{"question_id": qid} for qid in (self.question_ids or [])]


class QuestionInfo(BaseModel):
    question_id: str
    order: Optional[int] = None
    type: Optional[str] = None
    difficulty: Optional[str] = None
    knowledge_point: Optional[str] = None
    source_url: Optional[str] = None


class AnalysisResult(BaseModel):
    difficulty_score: float
    radar_data: List[dict]
    ai_comment: str


class PaperResponse(BaseModel):
    paper_id: int
    paper_name: str
    created_at: str
    questions: List[QuestionInfo]
    analysis: Optional[AnalysisResult] = None


class ChatRequest(BaseModel):
    conversation_id: int
    message: str
    subject: Optional[str] = "高中数学"
    # Optional model overrides (client-side selector).
    # When omitted/empty, backend defaults from env are used.
    model: Optional[str] = Field(default=None, max_length=200)
    sub_model: Optional[str] = Field(default=None, max_length=200)


class ConversationCreate(BaseModel):
    title: Optional[str] = "新对话"


class ConversationForkRequest(BaseModel):
    message_id: int
    title: Optional[str] = None


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SearchHistoryCreate(BaseModel):
    search_type: str
    search_query: str
    result_count: int


class DeepThinkRequest(BaseModel):
    """Request body for DeepThink (Tree-of-Thought) endpoint."""
    question: str
    subject: Optional[str] = "高中数学"
    image_url: Optional[str] = None
