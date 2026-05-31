"""Pydantic schemas for essay evaluation requests / responses."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Public enums                                                                 #
# --------------------------------------------------------------------------- #


EssayLanguage = Literal["zh", "en"]
EssayType = Literal[
    "argumentative",  # 议论文 / argumentative
    "narrative",      # 记叙文 / narrative
    "expository",     # 说明文 / expository
    "applied",        # 应用文 / applied (letter, report, ...)
    "other",
]
GradeBand = Literal[
    "primary",        # 小学
    "junior",         # 初中
    "senior",         # 高中（默认）
    "ielts",          # 雅思
    "toefl",          # 托福
    "other",
]


# --------------------------------------------------------------------------- #
# Request / response models                                                    #
# --------------------------------------------------------------------------- #


class EssayEvaluationRequest(BaseModel):
    """Inbound payload from API or task runner."""

    text: str = Field(..., min_length=10, max_length=20000)
    language: EssayLanguage = "zh"
    essay_type: EssayType = "argumentative"
    grade_band: GradeBand = "senior"
    subject: str = Field(default="语文", max_length=40)
    topic: str = Field(default="", max_length=200)
    rubric_max_score: int = Field(default=60, ge=10, le=150)
    requirements: str = Field(default="", max_length=1000)


class EssayScore(BaseModel):
    """Per-dimension score; ``score`` and ``max_score`` use the same scale.

    ``weight`` is informational (UI radar chart) – the final ``score_total`` is
    computed from raw scores so a single dimension cannot dominate the rubric.
    """

    name: str
    score: float
    max_score: float
    weight: float = 1.0
    comment: str = ""


class EssayParagraphFeedback(BaseModel):
    """Inline annotation for a single paragraph of the essay."""

    index: int = Field(..., ge=0)
    excerpt: str = Field(default="", max_length=400)
    issues: List[str] = Field(default_factory=list)
    suggestion: str = Field(default="", max_length=400)


class EssayEvaluationResult(BaseModel):
    """Final scoring envelope persisted in the history table."""

    score_total: float
    score_max: float
    grade: str = ""
    summary: str = ""
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    scores: List[EssayScore] = Field(default_factory=list)
    paragraph_feedback: List[EssayParagraphFeedback] = Field(default_factory=list)
    rewrite: str = ""
    model: str = ""
    language: EssayLanguage = "zh"
    essay_type: EssayType = "argumentative"
    grade_band: GradeBand = "senior"


__all__ = [
    "EssayEvaluationRequest",
    "EssayEvaluationResult",
    "EssayParagraphFeedback",
    "EssayScore",
    "EssayLanguage",
    "EssayType",
    "GradeBand",
]
