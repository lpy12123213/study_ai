from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.agent.types import CompressedContext


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _clip_list(items: List[str], limit: int) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for x in items:
        s = str(x or "").strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


@dataclass(frozen=True)
class StudyMaterialsPolicyConfig:
    auto_research: bool = True
    auto_revise: bool = True

    auto_research_max_points: int = 3
    auto_research_max_rounds: int = 2
    auto_revise_max_rounds: int = 1

    iterations_quick: int = 1
    iterations_standard: int = 2
    iterations_deep: int = 3
    iterations_research: int = 4
    iterations_cap: int = 5

    @classmethod
    def from_env(cls) -> "StudyMaterialsPolicyConfig":
        # Back-compat: keep honoring existing knobs.
        auto_research = _env_truthy(
            "STUDY_MATERIALS_POLICY_AUTO_RESEARCH", _env_truthy("STUDY_MATERIALS_AUTO_RESEARCH", True)
        )
        auto_revise = _env_truthy(
            "STUDY_MATERIALS_POLICY_AUTO_REVISE", _env_truthy("STUDY_MATERIALS_AUTO_REVISE", True)
        )

        return cls(
            auto_research=auto_research,
            auto_revise=auto_revise,
            auto_research_max_points=max(1, min(_env_int("STUDY_MATERIALS_AUTO_RESEARCH_MAX_POINTS", 3), 15)),
            auto_research_max_rounds=max(0, min(_env_int("STUDY_MATERIALS_POLICY_AUTO_RESEARCH_MAX_ROUNDS", 2), 10)),
            auto_revise_max_rounds=max(0, min(_env_int("STUDY_MATERIALS_POLICY_AUTO_REVISE_MAX_ROUNDS", 1), 10)),
            iterations_quick=max(1, min(_env_int("STUDY_MATERIALS_POLICY_ITERATIONS_QUICK", 1), 10)),
            iterations_standard=max(1, min(_env_int("STUDY_MATERIALS_POLICY_ITERATIONS_STANDARD", 2), 10)),
            iterations_deep=max(1, min(_env_int("STUDY_MATERIALS_POLICY_ITERATIONS_DEEP", 3), 10)),
            iterations_research=max(1, min(_env_int("STUDY_MATERIALS_POLICY_ITERATIONS_RESEARCH", 4), 10)),
            iterations_cap=max(1, min(_env_int("STUDY_MATERIALS_POLICY_ITERATIONS_CAP", 6), 20)),
        )


class StudyMaterialsPolicy:
    """Explicit adaptive policy for study-materials runs.

    This module centralizes the heuristics that decide:
    - iteration budget (how many Plan-Act-Reflect loops to allow)
    - whether to auto-research missing knowledge points within the same iteration
    - whether to auto-revise markdown within the same iteration (LLM review issues)
    """

    _MISSING_RE = re.compile(
        r"知识点[《「“\"](.+?)[》」”\"](?:资料来源不足|覆盖维度不足)",
        re.IGNORECASE,
    )

    def __init__(self, *, config: Optional[StudyMaterialsPolicyConfig] = None) -> None:
        self.config = config or StudyMaterialsPolicyConfig.from_env()

    def _policy_state(self, ctx: CompressedContext) -> Dict[str, Any]:
        state = ctx.working_memory.get("_study_policy")
        if isinstance(state, dict):
            return state
        state = {}
        ctx.working_memory["_study_policy"] = state
        return state

    def iteration_budget(self, ctx: CompressedContext, *, default_cap: int) -> int:
        opts = ctx.working_memory.get("study_options")
        opts = dict(opts) if isinstance(opts, dict) else {}
        preset = str(opts.get("preset") or "").strip().lower()
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = "standard"

        mode = str(opts.get("continue_mode") or "").strip().lower()
        if mode in {"improve", "deepen_research", "fix_export", "skip_export"}:
            # Continuation endpoints should stay snappy and user-driven: 1 loop per click.
            return 1

        if preset == "quick":
            budget = self.config.iterations_quick
        elif preset == "deep":
            budget = self.config.iterations_deep
        elif preset == "research":
            budget = self.config.iterations_research
        else:
            budget = self.config.iterations_standard

        budget = max(1, min(int(budget), int(self.config.iterations_cap or 1)))
        # NOTE: study-materials has its own budget knobs; we intentionally do not hard-cap to
        # AGENT_MAX_ITERATIONS here because many deployments want chat to be cheap but materials to be deep.
        _ = default_cap
        return budget

    def _parse_missing_kps(self, issues: Any) -> List[str]:
        if not isinstance(issues, list):
            return []
        missing: List[str] = []
        for it in issues:
            s = str(it or "").strip()
            if not s:
                continue
            m = self._MISSING_RE.search(s)
            if not m:
                continue
            kp = str(m.group(1) or "").strip()
            if kp:
                missing.append(kp)
        return _clip_list(missing, 50)

    def missing_kps_for_auto_research(self, ctx: CompressedContext) -> List[str]:
        if not self.config.auto_research:
            return []

        review = ctx.working_memory.get("review_content")
        if not isinstance(review, dict) or review.get("passed") is not False:
            return []
        if str(review.get("source") or "").strip().lower() != "heuristic":
            return []

        missing = self._parse_missing_kps(review.get("issues"))
        if not missing:
            return []

        state = self._policy_state(ctx)
        rounds_done = int(state.get("auto_research_rounds") or 0)
        if self.config.auto_research_max_rounds <= 0 or rounds_done >= int(self.config.auto_research_max_rounds):
            return []

        done_kps = state.get("auto_research_done_kps")
        done_set = {str(x or "").strip() for x in done_kps} if isinstance(done_kps, list) else set()
        missing = [kp for kp in missing if kp and kp not in done_set]
        if not missing:
            return []

        max_kps = max(1, int(self.config.auto_research_max_points or 3))
        return _clip_list(missing, max_kps)

    def mark_auto_research(self, ctx: CompressedContext, kps: List[str]) -> None:
        state = self._policy_state(ctx)
        state["auto_research_rounds"] = int(state.get("auto_research_rounds") or 0) + 1
        prev = state.get("auto_research_done_kps")
        done: List[str] = [str(x or "").strip() for x in prev] if isinstance(prev, list) else []
        done.extend([str(x or "").strip() for x in (kps or []) if str(x or "").strip()])
        state["auto_research_done_kps"] = _clip_list(done, 100)

    def issues_for_auto_revise(self, ctx: CompressedContext, *, planned_tools: Optional[set[str]] = None) -> List[str]:
        if not self.config.auto_revise:
            return []

        review = ctx.working_memory.get("review_content")
        if not isinstance(review, dict) or review.get("passed") is not False:
            return []

        source = str(review.get("source") or "").strip().lower()
        if not source or source == "heuristic":
            return []

        issues = review.get("issues")
        if not isinstance(issues, list) or not issues:
            return []

        markdown = str(ctx.working_memory.get("markdown") or "").strip()
        if not markdown:
            return []

        if planned_tools and "revise_markdown" in planned_tools:
            return []

        state = self._policy_state(ctx)
        rounds_done = int(state.get("auto_revise_rounds") or 0)
        if self.config.auto_revise_max_rounds <= 0 or rounds_done >= int(self.config.auto_revise_max_rounds):
            return []

        return [str(x or "").strip() for x in issues if str(x or "").strip()][:12]

    def mark_auto_revise(self, ctx: CompressedContext) -> None:
        state = self._policy_state(ctx)
        state["auto_revise_rounds"] = int(state.get("auto_revise_rounds") or 0) + 1
