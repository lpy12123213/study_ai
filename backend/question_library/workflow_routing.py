from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal

from backend.question_library.gen_common import DEFAULT_SEARCH_CONFIG

QuestionGenerationWorkflowMode = Literal["lightweight", "heavyweight"]

_LIGHTWEIGHT_OVERRIDES: Dict[str, Any] = {
    "preset": "quick-lightweight",
    "workflow_mode": "lightweight",
    "depth": 2,
    "beam_width": 3,
    "expand_budget": 24,
    "skill_branch_factor": 2,
    "reasoning_branch_factor": 1,
    "trap_branch_factor": 1,
    "surface_branch_factor": 1,
    "drafts_per_spec": 1,
    "enable_brainstorm": False,
    "brainstorm_seed_count": 0,
    "enable_diagrams": False,
    "solver_consensus_n": 1,
    "max_repair_rounds": 0,
    "judge_pass_score": 65,
    "max_concurrent_realize": 3,
    "max_concurrent_judge": 2,
}

_HEAVYWEIGHT_OVERRIDES: Dict[str, Any] = {
    "preset": "deep-heavyweight",
    "workflow_mode": "heavyweight",
    "enable_brainstorm": True,
    "enable_diagrams": True,
}

_EASY_TERMS = ("基础", "简单", "入门", "随堂", "课后练习", "小练习", "普通练习", "快速", "巩固")
_LIGHT_QUESTION_TYPES = ("选择题", "填空题", "判断题")
_HARD_TERMS = (
    "困难",
    "较难",
    "偏难",
    "压轴",
    "综合",
    "高区分度",
    "区分度",
    "创新",
    "探究",
    "开放",
    "证明",
    "多步骤",
    "分类讨论",
    "参数",
    "竞赛",
)
_REFERENCE_TERMS = ("真题", "高考", "模考", "联考", "参考题", "近三年", "近五年", "近5年", "近3年")


@dataclass(frozen=True)
class QuestionGenerationWorkflowRoute:
    workflow_mode: QuestionGenerationWorkflowMode
    requested_mode: str
    reason: str
    reasons: List[str]
    config: Dict[str, Any]
    use_reference_questions: bool

    @property
    def label(self) -> str:
        return "轻量工作流" if self.workflow_mode == "lightweight" else "重量工作流"

    def progress_stats(self) -> Dict[str, Any]:
        return {
            "workflow_mode": self.workflow_mode,
            "workflow_label": self.label,
            "reason": self.reason,
            "reasons": list(self.reasons),
            "use_reference_questions": self.use_reference_questions,
            "preset": str(self.config.get("preset") or ""),
        }


def _merge_config(overrides: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(DEFAULT_SEARCH_CONFIG)
    cfg.update(dict(overrides or {}))
    return cfg


def _normalize_workflow_mode(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in {"light", "lite", "quick", "fast", "lightweight"}:
        return "lightweight"
    if raw in {"heavy", "deep", "full", "advanced", "heavyweight"}:
        return "heavyweight"
    return "auto"


def _difficulty_is_hard(value: Any) -> bool:
    text = str(value or "").strip()
    return any(token in text for token in ("困难", "较难", "偏难", "压轴", "难"))


def _difficulty_is_easy(value: Any) -> bool:
    text = str(value or "").strip()
    return any(token in text for token in ("基础", "较易", "偏易", "简单", "易"))


def _contains_any(text: str, terms: tuple[str, ...]) -> List[str]:
    return [term for term in terms if term and term in text]


def route_question_generation_workflow(request: Dict[str, Any]) -> QuestionGenerationWorkflowRoute:
    req = dict(request or {})
    requested_mode = _normalize_workflow_mode(req.get("workflow_mode"))
    topic = str(req.get("topic") or "").strip()
    difficulty = str(req.get("difficulty") or "").strip()
    question_type = str(req.get("question_type") or "").strip()
    subject = str(req.get("subject") or "").strip()
    text = "\n".join([subject, topic, difficulty, question_type])

    try:
        count = int(req.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    count = max(0, count)

    reference_source = str(req.get("reference_source") or "any").strip() or "any"
    reference_year_range = str(req.get("reference_year_range") or "all").strip() or "all"
    reference_terms = _contains_any(text, _REFERENCE_TERMS)
    explicit_reference_scope = reference_source != "any" or reference_year_range != "all" or bool(reference_terms)
    requested_reference = bool(req.get("use_reference_questions"))

    if requested_mode in {"lightweight", "heavyweight"}:
        config = _merge_config(
            _LIGHTWEIGHT_OVERRIDES if requested_mode == "lightweight" else _HEAVYWEIGHT_OVERRIDES
        )
        use_reference_questions = bool(requested_reference and (requested_mode == "heavyweight" or explicit_reference_scope))
        return QuestionGenerationWorkflowRoute(
            workflow_mode=requested_mode,  # type: ignore[arg-type]
            requested_mode=requested_mode,
            reason=f"explicit:{requested_mode}",
            reasons=[f"explicit:{requested_mode}"],
            config=config,
            use_reference_questions=use_reference_questions,
        )

    heavy_reasons: List[str] = []
    if str(req.get("mode") or "").strip() == "infinite":
        heavy_reasons.append("infinite")
    if bool(req.get("stream_reasoning")):
        heavy_reasons.append("stream_reasoning")
    if count >= 3:
        heavy_reasons.append(f"count>={count}")
    if _difficulty_is_hard(difficulty):
        heavy_reasons.append(difficulty or "hard_difficulty")
    heavy_reasons.extend(_contains_any(text, _HARD_TERMS))
    if explicit_reference_scope and requested_reference:
        heavy_reasons.extend(reference_terms or [f"reference:{reference_source}:{reference_year_range}"])

    if heavy_reasons:
        reasons = list(dict.fromkeys([str(item) for item in heavy_reasons if str(item).strip()]))
        return QuestionGenerationWorkflowRoute(
            workflow_mode="heavyweight",
            requested_mode="auto",
            reason=";".join(reasons[:4]),
            reasons=reasons,
            config=_merge_config(_HEAVYWEIGHT_OVERRIDES),
            use_reference_questions=bool(requested_reference),
        )

    easy_terms = _contains_any(text, _EASY_TERMS)
    light_question_type = any(term in question_type for term in _LIGHT_QUESTION_TYPES)
    if count <= 2 and (easy_terms or _difficulty_is_easy(difficulty) or light_question_type):
        reasons = list(dict.fromkeys(easy_terms or [difficulty or question_type or "small_request"]))
        return QuestionGenerationWorkflowRoute(
            workflow_mode="lightweight",
            requested_mode="auto",
            reason=";".join(reasons[:4]),
            reasons=reasons,
            config=_merge_config(_LIGHTWEIGHT_OVERRIDES),
            use_reference_questions=bool(requested_reference and explicit_reference_scope),
        )

    return QuestionGenerationWorkflowRoute(
        workflow_mode="heavyweight",
        requested_mode="auto",
        reason="default_quality",
        reasons=["default_quality"],
        config=_merge_config(_HEAVYWEIGHT_OVERRIDES),
        use_reference_questions=bool(requested_reference),
    )
