from __future__ import annotations

import os
from typing import Any, Dict

from backend.agent.types import CompressedContext, UserProfile


def _env_truthy(name: str) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _normalize_preset(value: str) -> str:
    """Normalize study-materials presets.

    Supported:
    - quick: shorter, fewer sources, faster
    - standard: default
    - deep: deeper retrieval + longer explanations
    - research: more research-oriented (multi-pass retrieval + deeper synthesis)
    """

    v = (value or "").strip().lower()
    if v in {"quick", "fast", "brief"}:
        return "quick"
    if v in {"research", "deepresearch", "deep-research", "researchy"}:
        return "research"
    if v in {"deep", "detail", "detailed"}:
        return "deep"
    if v in {"standard", "normal", "default"}:
        return "standard"
    return ""


def _study_options_from_context(context: CompressedContext) -> Dict[str, Any]:
    opts = context.working_memory.get("study_options")
    return dict(opts) if isinstance(opts, dict) else {}


def _study_flags(context: CompressedContext) -> Dict[str, Any]:
    """Compute study-materials feature flags from env + per-task options."""

    opts = _study_options_from_context(context)
    preset = _normalize_preset(str(opts.get("preset") or os.getenv("STUDY_MATERIALS_PRESET") or ""))

    with_q = opts.get("with_questions")
    enable_questions = bool(with_q) if isinstance(with_q, bool) else _env_truthy("STUDY_MATERIALS_ENABLE_QUESTIONS")

    extra = opts.get("enable_extra_tools")
    enable_extra_tools = bool(extra) if isinstance(extra, bool) else _env_truthy("STUDY_MATERIALS_ENABLE_EXTRA_TOOLS")

    # Deep preset does not auto-enable extra tools by default
    # if preset in {"deep", "research"}:
    #     enable_extra_tools = True

    with_diagrams = opts.get("with_diagrams")
    enable_diagrams = bool(with_diagrams) if isinstance(with_diagrams, bool) else True

    max_points = opts.get("max_points")
    try:
        max_points_int = int(max_points) if max_points is not None else 0
    except Exception:
        max_points_int = 0

    return {
        "preset": preset or "standard",
        "enable_questions": enable_questions,
        "enable_extra_tools": enable_extra_tools,
        "enable_diagrams": enable_diagrams,
        "max_points": max_points_int,
        "requirements": str(opts.get("requirements") or "").strip(),
    }


def _difficulty_from_profile(profile: UserProfile) -> str:
    score = float(profile.ability_score or 0.5)
    if score < 0.4:
        return "简单"
    if score < 0.7:
        return "中等"
    return "困难"

