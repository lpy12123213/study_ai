from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CanvasBoardCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    subject: Optional[str] = Field(default=None, max_length=100)
    snapshot: Optional[Dict[str, Any]] = None


class CanvasBoardUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    subject: Optional[str] = Field(default=None, max_length=100)
    snapshot: Optional[Dict[str, Any]] = None
    expected_revision: Optional[int] = None


class CanvasBoardSummary(BaseModel):
    id: int
    title: str
    subject: str
    revision: int
    created_at: str
    updated_at: str


class CanvasBoardDetail(CanvasBoardSummary):
    snapshot: Dict[str, Any]


class CanvasBoardListResponse(BaseModel):
    success: bool = True
    boards: List[CanvasBoardSummary]


class CanvasBoardVersionsResponse(BaseModel):
    success: bool = True
    versions: List[dict]

