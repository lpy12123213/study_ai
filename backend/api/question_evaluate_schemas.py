from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class QuestionInput(BaseModel):
    question_id: str = ""
    stem: str = ""
    type: str = ""
    difficulty: str = ""
    knowledge_points: str = ""
    source: str = ""
    source_url: str = ""
    date: str = ""
    quality_score: Optional[int] = None
    quality_flags: List[str] = Field(default_factory=list)
    difficulty_value: Optional[float] = None


class QuestionEvaluateRequest(BaseModel):
    questions: List[QuestionInput] = Field(default_factory=list)
    subject: str = ""
    requirements: str = ""
    model: str = ""


class DimensionScore(BaseModel):
    name: str = ""
    score: int = 0
    comment: str = ""


class QuestionEvaluation(BaseModel):
    question_id: str = ""
    verdict: str = ""
    overall_score: int = 0
    dimensions: List[DimensionScore] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    summary: str = ""


class QuestionEvaluateResponse(BaseModel):
    results: List[QuestionEvaluation] = Field(default_factory=list)
    model: str = ""


class QuestionSearchRequest(BaseModel):
    query: str = ""
    subject: str = ""
    edu_level: str = ""
    difficulty: str = ""
    question_type: str = ""
    limit: int = 20
    max_pages: int = 2
    min_quality_score: int = 0


class QuestionSearchResponse(BaseModel):
    success: bool = True
    query: str = ""
    subject: str = ""
    count: int = 0
    questions: List[QuestionInput] = Field(default_factory=list)
    error: str = ""
