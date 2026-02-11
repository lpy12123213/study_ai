from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StudyMaterialsGenerateRequest(BaseModel):
    query: str = Field(..., description="要学习的知识点/主题（自然语言即可）")
    subject: str = Field("", description="可选：学科全名（如：高中数学）")
    preset: str = Field("", description="可选：生成预设 quick|standard|deep|research（影响检索深度与篇幅）")
    requirements: str = Field("", description="可选：额外要求（如：更通俗/更严谨/偏推导/偏直观等）")
    with_questions: Optional[bool] = Field(None, description="可选：是否生成例题/练习题（默认按环境变量）")
    with_diagrams: Optional[bool] = Field(None, description="可选：是否生成示意图（默认开启）")
    enable_extra_tools: Optional[bool] = Field(None, description="可选：是否启用额外检索工具（默认按环境变量）")
    max_points: Optional[int] = Field(None, description="可选：知识点数量上限（1-15）")

