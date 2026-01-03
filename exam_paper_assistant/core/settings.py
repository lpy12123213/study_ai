"""
Project-wide settings loaded from environment variables.

All other modules should prefer importing from here (or via the existing
`backend.config` compatibility layer).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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

    # Models
    main_model: str
    sub_model: str

    # Model params
    main_model_temperature: float
    main_model_max_tokens: int
    sub_model_temperature: float
    sub_model_max_tokens: int

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

    @classmethod
    def from_env(cls) -> "Settings":
        # Load from `.env` (if present) without overriding explicit env vars.
        load_dotenv(override=False)

        openrouter_api_key = _get_str("OPENROUTER_API_KEY", "")
        base_url = _get_str("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        fireworks_api_key = _get_str("FIREWORKS_API_KEY", "")
        fireworks_base_url = _get_str("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1").rstrip("/")
        zhipu_base_url = _get_str("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")

        chat_provider_raw = _get_str("CHAT_PROVIDER", "openrouter").lower()
        chat_provider = chat_provider_raw if chat_provider_raw in {"openrouter", "fireworks"} else "openrouter"
        chat_base_url = base_url if chat_provider == "openrouter" else fireworks_base_url
        chat_api_key = openrouter_api_key if chat_provider == "openrouter" else fireworks_api_key

        return cls(
            chat_provider=chat_provider,
            chat_api_key=chat_api_key,
            chat_base_url=chat_base_url,
            openrouter_api_key=openrouter_api_key,
            openrouter_base_url=base_url,
            main_model=_get_str("MAIN_MODEL", "openai/gpt-5-mini"),
            sub_model=_get_str("SUB_MODEL", "openai/gpt-5-mini"),
            main_model_temperature=_get_float("MAIN_MODEL_TEMPERATURE", 0.7),
            main_model_max_tokens=_get_int("MAIN_MODEL_MAX_TOKENS", 2000),
            sub_model_temperature=_get_float("SUB_MODEL_TEMPERATURE", 0.3),
            sub_model_max_tokens=_get_int("SUB_MODEL_MAX_TOKENS", 1000),
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
        )

    def summary(self) -> Dict[str, Any]:
        return {
            "chat_provider": self.chat_provider,
            "main_model": self.main_model,
            "sub_model": self.sub_model,
            "main_temperature": self.main_model_temperature,
            "sub_temperature": self.sub_model_temperature,
            "max_iterations": self.max_tool_iterations,
            "default_subject": self.default_subject,
            "difficulty_query_mode": self.difficulty_query_mode,
            "chat_configured": bool(self.chat_api_key),
            "openrouter_configured": bool(self.openrouter_api_key),
            "fireworks_configured": bool(self.fireworks_api_key),
            "zhipu_configured": bool(self.zhipu_api_key),
        }


settings = Settings.from_env()

# Chat provider (OpenAI-compatible)
CHAT_PROVIDER = settings.chat_provider
CHAT_API_KEY = settings.chat_api_key
CHAT_BASE_URL = settings.chat_base_url

# Back-compat module-level constants (used widely across the codebase).
OPENROUTER_API_KEY = settings.openrouter_api_key
OPENROUTER_BASE_URL = settings.openrouter_base_url

MAIN_MODEL = settings.main_model
SUB_MODEL = settings.sub_model

MAIN_MODEL_TEMPERATURE = settings.main_model_temperature
MAIN_MODEL_MAX_TOKENS = settings.main_model_max_tokens
SUB_MODEL_TEMPERATURE = settings.sub_model_temperature
SUB_MODEL_MAX_TOKENS = settings.sub_model_max_tokens

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


def get_config_summary() -> Dict[str, Any]:
    """Compatibility wrapper for older callers."""
    return settings.summary()
