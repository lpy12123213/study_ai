from __future__ import annotations

import os
from dataclasses import dataclass

from backend.core.settings import LESSON_PLAN_MODEL, SUB_MODEL


@dataclass(frozen=True)
class AgentConfig:
    # Plan-Act-Reflect
    max_iterations: int = 5
    parallel_tool_calls: bool = True
    # SubAgent concurrency for foreach_knowledge_point blocks (study-materials)
    subagent_concurrency: int = 3

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

    @classmethod
    def from_env(cls) -> "AgentConfig":
        def _get_int(name: str, default: int) -> int:
            raw = (os.getenv(name) or "").strip()
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        def _get_bool(name: str, default: bool) -> bool:
            raw = (os.getenv(name) or "").strip().lower()
            if not raw:
                return default
            return raw in {"1", "true", "yes", "y", "on"}

        def _get_str(name: str, default: str) -> str:
            raw = (os.getenv(name) or "").strip()
            return raw or default

        return cls(
            max_iterations=_get_int("AGENT_MAX_ITERATIONS", cls.max_iterations),
            parallel_tool_calls=_get_bool("AGENT_PARALLEL_TOOL_CALLS", cls.parallel_tool_calls),
            subagent_concurrency=_get_int(
                "STUDY_MATERIALS_SUBAGENT_CONCURRENCY",
                _get_int("AGENT_SUBAGENT_CONCURRENCY", cls.subagent_concurrency),
            ),
            sliding_window_size=_get_int("AGENT_SLIDING_WINDOW_SIZE", cls.sliding_window_size),
            token_threshold=_get_int("AGENT_TOKEN_THRESHOLD", cls.token_threshold),
            emergency_token_threshold=_get_int("AGENT_EMERGENCY_TOKEN_THRESHOLD", cls.emergency_token_threshold),
            compressed_history_max=_get_int("AGENT_COMPRESSED_HISTORY_MAX", cls.compressed_history_max),
            checkpoint_dir=_get_str("AGENT_CHECKPOINT_DIR", cls.checkpoint_dir),
            planner_model=_get_str("AGENT_PLANNER_MODEL", cls.planner_model),
            summarizer_model=_get_str("AGENT_SUMMARIZER_MODEL", cls.summarizer_model),
            reflector_model=_get_str("AGENT_REFLECTOR_MODEL", cls.reflector_model),
        )


# Back-compat with the plan doc snippet.
_cfg = AgentConfig.from_env()
AGENT_CONFIG = {
    "max_iterations": _cfg.max_iterations,
    "parallel_tool_calls": _cfg.parallel_tool_calls,
    "sliding_window_size": _cfg.sliding_window_size,
    "token_threshold": _cfg.token_threshold,
    "checkpoint_dir": _cfg.checkpoint_dir,
    "planner_model": _cfg.planner_model,
    "summarizer_model": _cfg.summarizer_model,
    "reflector_model": _cfg.reflector_model,
}
