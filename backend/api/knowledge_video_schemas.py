from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeVideoGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=300, description="知识视频主题")
    subject: str = Field("", max_length=100, description="可选：学科")
    source_markdown: str = Field("", max_length=80000, description="可选：参考资料 Markdown")
    source_archive_id: Optional[int] = Field(None, description="可选：自学资料归档 ID")
    duration_seconds: Optional[int] = Field(30, ge=10, le=180, description="目标视频时长")
    style: str = Field("clean", max_length=80, description="动画风格")
    requirements: str = Field("", max_length=4000, description="额外要求")
    quality: str = Field("low", max_length=30, description="Manim 渲染质量 low|medium|high")

