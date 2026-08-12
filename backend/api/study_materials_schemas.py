from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.core.text_utils import clip_text as _clip_text


class StudyMaterialsGenerateRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="要学习的知识点/主题（自然语言即可）")
    subject: str = Field("", max_length=100, description="可选：学科全名（如：高中数学）")
    preset: str = Field(
        "", max_length=50, description="可选：生成预设 quick|standard|deep|research（影响检索深度与篇幅）"
    )
    requirements: str = Field("", max_length=2000, description="可选：额外要求（如：更通俗/更严谨/偏推导/偏直观等）")
    with_questions: Optional[bool] = Field(None, description="可选：是否生成例题/练习题（默认按环境变量）")
    with_diagrams: Optional[bool] = Field(None, description="可选：是否生成示意图（默认开启）")
    enable_extra_tools: Optional[bool] = Field(None, description="可选：是否启用额外检索工具（默认按环境变量）")
    max_points: Optional[int] = Field(None, description="可选：知识点数量上限（1-15）")
    prefer_local_archive: Optional[bool] = Field(
        None,
        description="可选：是否优先从本地知识库/归档复用（默认 quick/standard 自动开；可用环境变量 STUDY_ARCHIVE_PREFER_LOCAL 覆盖）",
    )
    research_budget: Literal["", "lean", "balanced"] = Field(
        "",
        description="可选：研究调用预算 lean|balanced；lean 保留逐知识点检索并限制百科补充与网页深读",
    )


class StudyMaterialsConvertMarkdownToLatexRequest(BaseModel):
    markdown: str = Field(..., min_length=1, max_length=120000, description="Markdown 源文")
    topic: str = Field("", max_length=200, description="可选：主题/标题（用于 LaTeX 文档标题）")
    subject: str = Field("", max_length=100, description="可选：学科全名（如：高中数学）")


class StudyMaterialsConvertMarkdownToLatexResponse(BaseModel):
    tex_url: str = Field(..., description="生成的 .tex 下载链接")
    filename: str = Field(..., description="生成的 .tex 文件名")
    sha256: str = Field(..., description="文件 sha256")
    bytes: int = Field(..., description="文件大小（字节）")
    model: str = Field("", description="使用的模型")
    continuations: int = Field(0, description="续写次数")


class StudyMaterialsContinueRequest(BaseModel):
    mode: str = Field(
        "improve",
        max_length=50,
        description=(
            "继续模式：improve|deepen_research|fix_export|skip_export|resume_failed_stage|retry_search|replan_from_failure"
        ),
    )


def build_study_materials_options(request: StudyMaterialsGenerateRequest) -> dict:
    """Build the orchestrator options dict shared by both HTTP surfaces.

    `POST /api/study-materials/generate`（流式）与
    `POST /api/tasks/study-materials/generate`（任务提交）必须产出完全一致的
    options：requirements 截断到 600 字符，max_points 夹在 1-15，非法/非正
    max_points 直接丢弃。
    """

    options: dict = {}
    if (request.preset or "").strip():
        options["preset"] = str(request.preset or "").strip()
    if (request.requirements or "").strip():
        options["requirements"] = _clip_text(str(request.requirements or "").strip(), max_chars=600)
    if request.with_questions is not None:
        options["with_questions"] = bool(request.with_questions)
    if request.with_diagrams is not None:
        options["with_diagrams"] = bool(request.with_diagrams)
    if request.enable_extra_tools is not None:
        options["enable_extra_tools"] = bool(request.enable_extra_tools)
    if request.max_points is not None:
        try:
            n = int(request.max_points)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            options["max_points"] = max(1, min(n, 15))
    if request.prefer_local_archive is not None:
        options["preferLocalArchive"] = bool(request.prefer_local_archive)
    if request.research_budget:
        options["research_budget"] = request.research_budget
    return options


def invalid_continue_mode_detail(mode: str) -> str:
    """400 detail for unknown continue modes (keeps the stable `invalid_continue_mode` prefix)."""

    from backend.generation.study_materials.orchestrator import _CONTINUE_MODES

    valid = ",".join(sorted(_CONTINUE_MODES))
    return f"invalid_continue_mode: 未知续作模式 {str(mode or '').strip()!r}；可选模式：{valid}"
