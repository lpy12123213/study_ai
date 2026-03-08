from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AvailableFiltersRequest(BaseModel):
    subject: str = ""
    edu_level: str = ""


class ComposeBlueprintRequest(BaseModel):
    blueprint: List[Dict[str, Any]]
    subject: str = ""
    edu_level: str = ""
    learn_grade: str = ""
    learn_grade_id: int = 0
    textbook_version: str = ""
    elective_mode: str = ""
    elective_keywords: Optional[List[str]] = None
    exclude_elective: bool = False
    year: int = 0
    province: str = ""
    province_id: int = -1
    paper_type_id: int = 0
    term: int = 0
    order_by: int = 2
    max_pages: int = 2
    per_slot_expand: int = 3
    min_quality_score: int = 0
    dedup_by_stem: bool = True
    strict_subject: bool = True
    slot_concurrency: int = 0
    slot_delay_s: float = 0.0
    slot_retries: int = 1
