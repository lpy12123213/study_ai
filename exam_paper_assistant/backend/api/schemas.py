from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class QuestionItem(BaseModel):
    question_id: str
    type: Optional[str] = ""
    difficulty: Optional[str] = ""


class PaperCreate(BaseModel):
    paper_name: str
    questions: List[QuestionItem]


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


class ConversationCreate(BaseModel):
    title: Optional[str] = "新对话"

