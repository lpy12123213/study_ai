from __future__ import annotations

import os
from dataclasses import dataclass, field

from backend.core.settings import LESSON_PLAN_MODEL, MODEL_TIER_MAP, SUB_MODEL, env_bool, env_int


@dataclass(frozen=True)
class AgentConfig:
    # Plan-Act-Reflect
    max_iterations: int = 5
    parallel_tool_calls: bool = True
    # SubAgent concurrency for foreach_knowledge_point blocks (study-materials)
    subagent_concurrency: int = 3
    # Agent execution mode:
    # - "plan": Plan-Act-Reflect (existing behavior)
    # - "react": ReAct loop (LLM decides next tool dynamically)
    agent_mode: str = "react"
    # ReAct safety cap (prevents infinite tool loops).
    react_max_iterations: int = 20
    # ReAct budgets (safety caps).
    react_llm_call_budget: int = 25
    react_retry_budget_per_tool: int = 2
    # Skills-ification: when true, ReAct injects only the loaded-skill tools and
    # exposes the `load_skill` inline action (AGENT_SKILLS_MODE=1). Default off
    # keeps the legacy full tool list for A/B comparison and fast rollback.
    skills_mode: bool = False

    # Context compression
    sliding_window_size: int = 10
    # L2 soft-compaction threshold (requested: 32k tokens)
    token_threshold: int = 32000
    # L3 hard-compaction / checkpoint threshold (requested: 48k tokens)
    emergency_token_threshold: int = 48000
    compressed_history_max: int = 5
    checkpoint_dir: str = "data/checkpoints"

    # Models
    planner_model: str = LESSON_PLAN_MODEL
    summarizer_model: str = SUB_MODEL
    reflector_model: str = LESSON_PLAN_MODEL
    model_tier_map: dict[str, str] = field(default_factory=lambda: dict(MODEL_TIER_MAP))

    def model_for_tier(self, tier: str, *, fallback: str = "") -> str:
        key = str(tier or "").strip().lower()
        model = str((self.model_tier_map or {}).get(key) or "").strip()
        return model or str(fallback or "").strip()

    @classmethod
    def from_env(cls) -> "AgentConfig":
        def _get_str(name: str, default: str) -> str:
            raw = (os.getenv(name) or "").strip()
            return raw or default

        def _normalize_mode(raw: str) -> str:
            v = str(raw or "").strip().lower().replace("-", "").replace("_", "")
            if v in {"react", "reac"}:
                return "react"
            if v in {"plan", "planner", "planactreflect", "par"}:
                return "plan"
            return "plan"

        return cls(
            max_iterations=env_int("AGENT_MAX_ITERATIONS", cls.max_iterations),
            parallel_tool_calls=env_bool("AGENT_PARALLEL_TOOL_CALLS", cls.parallel_tool_calls),
            subagent_concurrency=env_int(
                "STUDY_MATERIALS_SUBAGENT_CONCURRENCY",
                env_int("AGENT_SUBAGENT_CONCURRENCY", cls.subagent_concurrency),
            ),
            agent_mode=_normalize_mode(_get_str("AGENT_MODE", cls.agent_mode)),
            react_max_iterations=env_int("AGENT_REACT_MAX_ITERATIONS", cls.react_max_iterations),
            react_llm_call_budget=env_int("AGENT_REACT_LLM_CALL_BUDGET", cls.react_llm_call_budget),
            react_retry_budget_per_tool=env_int(
                "AGENT_REACT_RETRY_BUDGET_PER_TOOL",
                cls.react_retry_budget_per_tool,
            ),
            skills_mode=env_bool("AGENT_SKILLS_MODE", cls.skills_mode),
            sliding_window_size=env_int("AGENT_SLIDING_WINDOW_SIZE", cls.sliding_window_size),
            token_threshold=env_int("AGENT_TOKEN_THRESHOLD", cls.token_threshold),
            emergency_token_threshold=env_int("AGENT_EMERGENCY_TOKEN_THRESHOLD", cls.emergency_token_threshold),
            compressed_history_max=env_int("AGENT_COMPRESSED_HISTORY_MAX", cls.compressed_history_max),
            checkpoint_dir=_get_str("AGENT_CHECKPOINT_DIR", cls.checkpoint_dir),
            planner_model=_get_str("AGENT_PLANNER_MODEL", cls.planner_model),
            summarizer_model=_get_str("AGENT_SUMMARIZER_MODEL", cls.summarizer_model),
            reflector_model=_get_str("AGENT_REFLECTOR_MODEL", cls.reflector_model),
            model_tier_map=dict(MODEL_TIER_MAP),
        )


# Back-compat with the plan doc snippet.
_cfg = AgentConfig.from_env()
AGENT_CONFIG = {
    "max_iterations": _cfg.max_iterations,
    "parallel_tool_calls": _cfg.parallel_tool_calls,
    "agent_mode": _cfg.agent_mode,
    "react_max_iterations": _cfg.react_max_iterations,
    "react_llm_call_budget": _cfg.react_llm_call_budget,
    "react_retry_budget_per_tool": _cfg.react_retry_budget_per_tool,
    "skills_mode": _cfg.skills_mode,
    "sliding_window_size": _cfg.sliding_window_size,
    "token_threshold": _cfg.token_threshold,
    "checkpoint_dir": _cfg.checkpoint_dir,
    "planner_model": _cfg.planner_model,
    "summarizer_model": _cfg.summarizer_model,
    "reflector_model": _cfg.reflector_model,
    "model_tier_map": dict(_cfg.model_tier_map),
}
