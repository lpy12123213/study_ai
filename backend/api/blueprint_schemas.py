from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BlueprintCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=100)
    topic: Optional[str] = Field(default="", max_length=200)
    slots: List[Dict[str, Any]] = Field(default_factory=list)


class BlueprintResponse(BaseModel):
    id: str
    name: str
    subject: str
    topic: str
    slots: List[Dict[str, Any]]
    createdAt: str
    updatedAt: str
