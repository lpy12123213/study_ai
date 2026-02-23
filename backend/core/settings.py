"""
Project-wide settings loaded from environment variables.

All other modules should prefer importing from here (or via the existing
`backend.config` compatibility layer).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv


def _get_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Chat provider (OpenAI-compatible)
    chat_provider: str
    chat_api_key: str
    chat_base_url: str

    # OpenRouter
    openrouter_api_key: str
    openrouter_base_url: str

    # Moonshot (official OpenAI-compatible)
    moonshot_api_key: str
    moonshot_base_url: str

    # Models
    main_model: str
    sub_model: str

    # DeepThink / Tree-of-Thoughts
    deepthink_generator_model: str
    deepthink_generator_temperature: float
    deepthink_generator_max_tokens: int
    deepthink_evaluator_model: str
    deepthink_evaluator_temperature: float
    deepthink_evaluator_max_tokens: int
    deepthink_reasoning_effort: str
    tot_branch_factor: int
    tot_beam_width: int
    tot_max_depth: int
    tot_prune_threshold: float
    tot_timeout_seconds: int

    # Lesson plan / study-materials provider (OpenAI-compatible)
    lesson_plan_provider: str
    lesson_plan_api_key: str
    lesson_plan_base_url: str
    lesson_plan_model: str
    lesson_plan_v2_subagent_concurrency: int

    # Model params
    main_model_temperature: float
    main_model_max_tokens: int
    sub_model_temperature: float
    sub_model_max_tokens: int

    # Optional overrides for lesson-plan style generation (fallback to MAIN_MODEL_* if unset)
    lesson_plan_temperature: float
    lesson_plan_max_tokens: int

    # Tool loop limits / timeouts
    max_tool_iterations: int
    api_timeout_seconds: int
    sub_ai_timeout_seconds: int

    # Crawler defaults
    default_subject: str
    difficulty_query_mode: str

    # Reviewer (MCP tool)
    review_provider: str
    fireworks_api_key: str
    fireworks_base_url: str
    review_model: str
    review_model_temperature: float
    review_model_max_tokens: int
    review_timeout_seconds: int
    review_max_stem_chars: int
    review_http_referer: str
    review_x_title: str

    # Zhipu BigModel (for MCP web-search tool)
    zhipu_api_key: str
    zhipu_base_url: str
    zhipu_model: str
    zhipu_timeout_seconds: int

    # Metaso AI search (direct API; used by study-materials web_search_knowledge)
    metaso_api_key: str
    metaso_base_url: str
    metaso_timeout_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        # Load from repo-root `.env` (if present) without overriding explicit env vars.
        #
        # External MCP clients often spawn the stdio server with an arbitrary CWD,
        # so relying on python-dotenv's default CWD search can miss the project's `.env`.
        repo_root = Path(__file__).resolve().parents[2]
        dotenv_path = repo_root / ".env"
        if not dotenv_path.exists():
            # Legacy fallback (older setups placed `.env` under `backend/`).
            dotenv_path = repo_root / "backend" / ".env"
        if dotenv_path.exists():
            load_dotenv(dotenv_path=str(dotenv_path), override=False)
        else:
            load_dotenv(override=False)

        openrouter_api_key = _get_str("OPENROUTER_API_KEY", "")
        base_url = _get_str("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        moonshot_api_key = _get_str("MOONSHOT_API_KEY", _get_str("MOONSHOT_API", ""))
        moonshot_base_url = _get_str("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1").rstrip("/")
        fireworks_api_key = _get_str("FIREWORKS_API_KEY", "")
        fireworks_base_url = _get_str("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1").rstrip("/")
        zhipu_base_url = _get_str("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
        metaso_base_url = _get_str("METASO_BASE_URL", "https://metaso.cn/api/v1").rstrip("/")

        # Metaso API key: prefer METASO_API_KEY; keep legacy alias METASO_API for compatibility.
        metaso_api_key = _get_str("METASO_API_KEY", _get_str("METASO_API", ""))
        metaso_timeout_seconds = _get_int("METASO_TIMEOUT", 30)

        chat_provider_raw = _get_str("CHAT_PROVIDER", "openrouter").lower()
        chat_provider = (
            chat_provider_raw if chat_provider_raw in {"openrouter", "fireworks", "moonshot"} else "openrouter"
        )
        if chat_provider == "fireworks":
            chat_base_url = fireworks_base_url
            chat_api_key = fireworks_api_key
        elif chat_provider == "moonshot":
            chat_base_url = moonshot_base_url
            chat_api_key = moonshot_api_key
        else:
            chat_base_url = base_url
            chat_api_key = openrouter_api_key

        lesson_plan_provider_raw = _get_str("LESSON_PLAN_PROVIDER", chat_provider).lower()
        lesson_plan_provider = (
            lesson_plan_provider_raw
            if lesson_plan_provider_raw in {"openrouter", "fireworks", "moonshot"}
            else chat_provider
        )
        if lesson_plan_provider == "fireworks":
            lesson_plan_base_url = fireworks_base_url
            lesson_plan_api_key = fireworks_api_key
        elif lesson_plan_provider == "moonshot":
            lesson_plan_base_url = moonshot_base_url
            lesson_plan_api_key = moonshot_api_key
        else:
            lesson_plan_base_url = base_url
            lesson_plan_api_key = openrouter_api_key
        lesson_plan_model = _get_str("LESSON_PLAN_MODEL", _get_str("MAIN_MODEL", "openai/gpt-5-mini"))
        lesson_plan_concurrency = _get_int("LESSON_PLAN_V2_SUBAGENT_CONCURRENCY", 3)

        main_model = _get_str("MAIN_MODEL", "openai/gpt-5-mini")
        deepthink_generator_model = _get_str("DEEPTHINK_GENERATOR_MODEL", main_model)
        deepthink_evaluator_model = _get_str("DEEPTHINK_EVALUATOR_MODEL", "")

        deepthink_generator_temperature = _get_float("DEEPTHINK_GENERATOR_TEMPERATURE", 0.4)
        deepthink_generator_max_tokens = _get_int("DEEPTHINK_GENERATOR_MAX_TOKENS", 1400)
        deepthink_evaluator_temperature = _get_float("DEEPTHINK_EVALUATOR_TEMPERATURE", 0.2)
        deepthink_evaluator_max_tokens = _get_int("DEEPTHINK_EVALUATOR_MAX_TOKENS", 900)
        deepthink_reasoning_effort = _get_str("DEEPTHINK_REASONING_EFFORT", "high")

        tot_branch_factor = _get_int("TOT_BRANCH_FACTOR", 3)
        tot_beam_width = _get_int("TOT_BEAM_WIDTH", 3)
        tot_max_depth = _get_int("TOT_MAX_DEPTH", 4)
        tot_prune_threshold = _get_float("TOT_PRUNE_THRESHOLD", 5.0)
        tot_timeout_seconds = _get_int("TOT_TIMEOUT", 60)

        return cls(
            chat_provider=chat_provider,
            chat_api_key=chat_api_key,
            chat_base_url=chat_base_url,
            openrouter_api_key=openrouter_api_key,
            openrouter_base_url=base_url,
            moonshot_api_key=moonshot_api_key,
            moonshot_base_url=moonshot_base_url,
            main_model=main_model,
            sub_model=_get_str("SUB_MODEL", "openai/gpt-5-mini"),
            deepthink_generator_model=deepthink_generator_model,
            deepthink_generator_temperature=deepthink_generator_temperature,
            deepthink_generator_max_tokens=deepthink_generator_max_tokens,
            deepthink_evaluator_model=deepthink_evaluator_model,
            deepthink_evaluator_temperature=deepthink_evaluator_temperature,
            deepthink_evaluator_max_tokens=deepthink_evaluator_max_tokens,
            deepthink_reasoning_effort=deepthink_reasoning_effort,
            tot_branch_factor=tot_branch_factor,
            tot_beam_width=tot_beam_width,
            tot_max_depth=tot_max_depth,
            tot_prune_threshold=tot_prune_threshold,
            tot_timeout_seconds=tot_timeout_seconds,
            lesson_plan_provider=lesson_plan_provider,
            lesson_plan_api_key=lesson_plan_api_key,
            lesson_plan_base_url=lesson_plan_base_url,
            lesson_plan_model=lesson_plan_model,
            lesson_plan_v2_subagent_concurrency=lesson_plan_concurrency,
            main_model_temperature=_get_float("MAIN_MODEL_TEMPERATURE", 0.7),
            main_model_max_tokens=_get_int("MAIN_MODEL_MAX_TOKENS", 2000),
            sub_model_temperature=_get_float("SUB_MODEL_TEMPERATURE", 0.3),
            sub_model_max_tokens=_get_int("SUB_MODEL_MAX_TOKENS", 1000),
            lesson_plan_temperature=_get_float("LESSON_PLAN_TEMPERATURE", _get_float("MAIN_MODEL_TEMPERATURE", 0.7)),
            lesson_plan_max_tokens=_get_int("LESSON_PLAN_MAX_TOKENS", _get_int("MAIN_MODEL_MAX_TOKENS", 2000)),
            max_tool_iterations=_get_int("MAX_TOOL_ITERATIONS", 10),
            api_timeout_seconds=_get_int("API_TIMEOUT", 120),
            sub_ai_timeout_seconds=_get_int("SUB_AI_TIMEOUT", 60),
            default_subject=_get_str("DEFAULT_SUBJECT", "高中数学"),
            difficulty_query_mode=_get_str("DIFFICULTY_QUERY_MODE", "multi").lower(),
            review_provider=_get_str("REVIEW_PROVIDER", "fireworks").lower(),
            fireworks_api_key=fireworks_api_key,
            fireworks_base_url=fireworks_base_url,
            # Fireworks model IDs change over time; default to a currently listed, chat-capable model.
            review_model=_get_str("REVIEW_MODEL", "accounts/fireworks/models/llama-v3p3-70b-instruct"),
            review_model_temperature=_get_float("REVIEW_MODEL_TEMPERATURE", 0.2),
            review_model_max_tokens=_get_int("REVIEW_MODEL_MAX_TOKENS", 1800),
            review_timeout_seconds=_get_int("REVIEW_TIMEOUT", 90),
            review_max_stem_chars=_get_int("REVIEW_MAX_STEM_CHARS", 900),
            review_http_referer=_get_str("REVIEW_HTTP_REFERER", "http://localhost:8000"),
            review_x_title=_get_str("REVIEW_X_TITLE", "Exam Paper Assistant - Reviewer"),
            zhipu_api_key=_get_str("ZHIPU_API_KEY", ""),
            zhipu_base_url=zhipu_base_url,
            zhipu_model=_get_str("ZHIPU_MODEL", "glm-4.5"),
            zhipu_timeout_seconds=_get_int("ZHIPU_TIMEOUT", 60),
            metaso_api_key=metaso_api_key,
            metaso_base_url=metaso_base_url,
            metaso_timeout_seconds=metaso_timeout_seconds,
        )

    def summary(self) -> Dict[str, Any]:
        return {
            "chat_provider": self.chat_provider,
            "main_model": self.main_model,
            "sub_model": self.sub_model,
            "lesson_plan_provider": self.lesson_plan_provider,
            "lesson_plan_model": self.lesson_plan_model,
            "main_temperature": self.main_model_temperature,
            "sub_temperature": self.sub_model_temperature,
            "max_iterations": self.max_tool_iterations,
            "default_subject": self.default_subject,
            "difficulty_query_mode": self.difficulty_query_mode,
            "chat_configured": bool(self.chat_api_key),
            "lesson_plan_configured": bool(self.lesson_plan_api_key),
            "openrouter_configured": bool(self.openrouter_api_key),
            "moonshot_configured": bool(self.moonshot_api_key),
            "fireworks_configured": bool(self.fireworks_api_key),
            "zhipu_configured": bool(self.zhipu_api_key),
            "metaso_configured": bool(self.metaso_api_key),
        }


settings = Settings.from_env()

# Chat provider (OpenAI-compatible)
CHAT_PROVIDER = settings.chat_provider
CHAT_API_KEY = settings.chat_api_key
CHAT_BASE_URL = settings.chat_base_url

# Back-compat module-level constants (used widely across the codebase).
OPENROUTER_API_KEY = settings.openrouter_api_key
OPENROUTER_BASE_URL = settings.openrouter_base_url

MOONSHOT_API_KEY = settings.moonshot_api_key
MOONSHOT_BASE_URL = settings.moonshot_base_url

MAIN_MODEL = settings.main_model
SUB_MODEL = settings.sub_model

# Lesson plan / study-materials provider (OpenAI-compatible)
LESSON_PLAN_PROVIDER = settings.lesson_plan_provider
LESSON_PLAN_API_KEY = settings.lesson_plan_api_key
LESSON_PLAN_BASE_URL = settings.lesson_plan_base_url
LESSON_PLAN_MODEL = settings.lesson_plan_model
LESSON_PLAN_V2_SUBAGENT_CONCURRENCY = settings.lesson_plan_v2_subagent_concurrency

MAIN_MODEL_TEMPERATURE = settings.main_model_temperature
MAIN_MODEL_MAX_TOKENS = settings.main_model_max_tokens
SUB_MODEL_TEMPERATURE = settings.sub_model_temperature
SUB_MODEL_MAX_TOKENS = settings.sub_model_max_tokens

LESSON_PLAN_TEMPERATURE = settings.lesson_plan_temperature
LESSON_PLAN_MAX_TOKENS = settings.lesson_plan_max_tokens

MAX_TOOL_ITERATIONS = settings.max_tool_iterations
API_TIMEOUT = settings.api_timeout_seconds
SUB_AI_TIMEOUT = settings.sub_ai_timeout_seconds

DEFAULT_SUBJECT = settings.default_subject
DIFFICULTY_QUERY_MODE = settings.difficulty_query_mode

# Reviewer settings (MCP tool)
REVIEW_PROVIDER = settings.review_provider
FIREWORKS_API_KEY = settings.fireworks_api_key
FIREWORKS_BASE_URL = settings.fireworks_base_url
REVIEW_MODEL = settings.review_model
REVIEW_MODEL_TEMPERATURE = settings.review_model_temperature
REVIEW_MODEL_MAX_TOKENS = settings.review_model_max_tokens
REVIEW_TIMEOUT = settings.review_timeout_seconds
REVIEW_MAX_STEM_CHARS = settings.review_max_stem_chars
REVIEW_HTTP_REFERER = settings.review_http_referer
REVIEW_X_TITLE = settings.review_x_title

# Zhipu BigModel settings (MCP web-search tool)
ZHIPU_API_KEY = settings.zhipu_api_key
ZHIPU_BASE_URL = settings.zhipu_base_url
ZHIPU_MODEL = settings.zhipu_model
ZHIPU_TIMEOUT = settings.zhipu_timeout_seconds

# Metaso AI search settings (direct API)
METASO_API_KEY = settings.metaso_api_key
METASO_BASE_URL = settings.metaso_base_url
METASO_TIMEOUT = settings.metaso_timeout_seconds


def get_config_summary() -> Dict[str, Any]:
    """Compatibility wrapper for older callers."""
    return settings.summary()
