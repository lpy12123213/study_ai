from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class QuestionGenerationStage:
    stage_id: str
    label: str
    group: str
    order: int
    description: str


QUESTION_GENERATION_STAGES = [
    QuestionGenerationStage(
        stage_id="source_pack",
        label="素材整理",
        group="prepare",
        order=1,
        description="整理任务主题、自学资料和知识点上下文，形成后续生成可用的素材包。",
    ),
    QuestionGenerationStage(
        stage_id="curriculum_context",
        label="课标对齐",
        group="prepare",
        order=2,
        description="依据新课标补充出题要求、知识范围与前置知识，约束后续生成边界。",
    ),
    QuestionGenerationStage(
        stage_id="reference_crawl",
        label="参考题爬取",
        group="reference",
        order=3,
        description="按学科、知识点、年份和来源范围检索可参考的真题或模拟题。",
    ),
    QuestionGenerationStage(
        stage_id="reference_analysis",
        label="参考题分析",
        group="reference",
        order=4,
        description="提取参考题的题型结构、难度分布、常见设问方式和格式约束。",
    ),
    QuestionGenerationStage(
        stage_id="brainstorm",
        label="直觉原子设计",
        group="design",
        order=5,
        description="设计学生可感知、检验并迁移的内部模型、决定性线索与常见错误直觉。",
    ),
    QuestionGenerationStage(
        stage_id="spec_search",
        label="练习包设计",
        group="design",
        order=6,
        description="把直觉原子展开为预测、模型显化、最小检验和迁移任务，并筛选候选结构。",
    ),
    QuestionGenerationStage(
        stage_id="draft_realization",
        label="练习包生成",
        group="generation",
        order=7,
        description="按候选结构生成兼容题干、答案和解析的分阶段直觉练习包。",
    ),
    QuestionGenerationStage(
        stage_id="diagram_generation",
        label="配图生成",
        group="generation",
        order=8,
        description="为需要图示的题目补充可渲染的配图资源，不阻断主生成链路。",
    ),
    QuestionGenerationStage(
        stage_id="judge",
        label="快速校验",
        group="quality",
        order=9,
        description="轻量检查课内正确性、直觉原子与题目一致、真实结构发现及有效迁移，失败时最多修复一次。",
    ),
    QuestionGenerationStage(
        stage_id="final_selection",
        label="练习包去重",
        group="quality",
        order=10,
        description="按直觉结构差异和目标数量去除会话内重复练习包。",
    ),
    QuestionGenerationStage(
        stage_id="pending_review",
        label="待审核预览",
        group="review",
        order=11,
        description="保存生成会话和草稿预览，等待人工审核、局部重生成或入库。",
    ),
]

_STAGE_BY_ID = {stage.stage_id: stage for stage in QUESTION_GENERATION_STAGES}


def get_question_generation_stage(stage_id: str, *, fallback_label: str = "") -> QuestionGenerationStage:
    normalized = str(stage_id or "").strip()
    stage = _STAGE_BY_ID.get(normalized)
    if stage:
        return stage
    label = str(fallback_label or normalized or "进度更新").strip()
    return QuestionGenerationStage(
        stage_id=normalized or "progress",
        label=label,
        group="other",
        order=999,
        description="未归类的任务进度更新。",
    )


def _scalar_summary_value(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(round(value, 3))
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed[:80] if trimmed else None
    return None


def format_stage_summary(stats: Optional[dict]) -> str:
    if not isinstance(stats, dict) or not stats:
        return ""

    priority = [
        "enabled",
        "reference_count",
        "seed_count",
        "kept_specs",
        "draft_count",
        "diagrams_total",
        "evaluated",
        "accepted",
        "rejected",
        "final_count",
        "batches",
    ]
    keys = [key for key in priority if key in stats]
    keys.extend(sorted(key for key in stats.keys() if key not in set(keys)))

    parts = []
    for key in keys:
        value = _scalar_summary_value(stats.get(key))
        if value is None:
            continue
        parts.append(f"{key}={value}")
        if len(parts) >= 5:
            break
    return " · ".join(parts)


def build_stage_progress_payload(
    stage_id: str,
    *,
    progress: float,
    stats: Optional[dict] = None,
    sample: Optional[dict] = None,
    label: str = "",
) -> Dict[str, Any]:
    stage = get_question_generation_stage(stage_id, fallback_label=label)
    payload: Dict[str, Any] = {
        "phase": stage.stage_id,
        "label": stage.label,
        "stage_id": stage.stage_id,
        "stage_label": stage.label,
        "stage_group": stage.group,
        "stage_order": stage.order,
        "description": stage.description,
        "summary": format_stage_summary(stats),
        "progress": float(progress),
        "stats": dict(stats or {}),
    }
    if isinstance(sample, dict) and sample:
        payload["sample"] = dict(sample)
    return payload
