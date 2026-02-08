from __future__ import annotations

from pydantic import BaseModel, Field


class StudyMaterialsGenerateRequest(BaseModel):
    query: str = Field(..., description="要学习的知识点/主题（自然语言即可）")
    subject: str = Field("", description="可选：学科全名（如：高中数学）")

