"""
Project-wide settings loaded from environment variables.

All other modules should prefer importing from here (or via the existing
`backend.config` compatibility layer).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

from backend.core.secrets import SecretString
from backend.llm.model_config import (
    DEFAULT_PROVIDER_BASE_URLS,
    ProviderConfig,
    load_model_json_config,
    resolve_model_config_path,
)

_dotenv_loaded = False


def load_project_dotenv(*, override: bool = False) -> None:
    """Load `.env` from the repo root with a stable resolution strategy.

    We keep dotenv loading centralized to avoid inconsistent CWD-dependent behavior.
    """

    global _dotenv_loaded
    if _dotenv_loaded and not override:
        return

    repo_root = Path(__file__).resolve().parents[2]
    dotenv_path = repo_root / ".env"
    if not dotenv_path.exists():
        # Legacy fallback (older setups placed `.env` under `backend/`).
        dotenv_path = repo_root / "backend" / ".env"

    if dotenv_path.exists():
        load_dotenv(dotenv_path=str(dotenv_path), override=override)
    else:
        load_dotenv(override=override)

    _dotenv_loaded = True


def _get_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def env_int(name: str, default: int) -> int:
    """Read an integer env var with a default (public deduplicated helper).

    Use this instead of redefining `_env_int` / `_get_int` / `_int_env` in each module.
    """
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


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean env var with a default (public deduplicated helper).

    Use this instead of redefining `_env_truthy` / `_get_bool` in each module.
    Accepts 1/true/yes/y/on (case-insensitive) as truthy.
    """
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    raw = raw.strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on"}


def _normalize_reasoning_effort(value: str, *, default: str = "xhigh") -> str:
    v = str(value or "").strip().lower().replace("-", "").replace("_", "")
    if not v:
        v = default
    if v in {"max", "maximum", "highest"}:
        v = "xhigh"
    allowed = {"none", "minimal", "low", "medium", "high", "xhigh"}
    if v not in allowed:
        v = default
    return v


def _normalize_model_tier_map(defaults: Dict[str, str], overrides: Dict[str, Any]) -> Dict[str, str]:
    allowed = {"fast", "cheap", "main", "heavy"}
    out: Dict[str, str] = {}
    for key in allowed:
        value = str(defaults.get(key) or "").strip()
        if value:
            out[key] = value
    for key, value in (overrides or {}).items():
        tier = str(key or "").strip().lower()
        model = str(value or "").strip()
        if tier in allowed and model:
            out[tier] = model
    return out


def _pick_provider_scoped(value: Any, provider_name: str) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        key = str(provider_name or "").strip().lower()
        selected = value.get(key)
        if isinstance(selected, str) and selected.strip():
            return selected.strip()
        selected = value.get("default")
        if isinstance(selected, str) and selected.strip():
            return selected.strip()
        for candidate in value.values():
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def _model_param_float(params: Dict[str, Any], key: str, default: float) -> float:
    try:
        value = float(params.get(key, default))
    except (TypeError, ValueError):
        value = float(default)
    return value


def _model_param_int(params: Dict[str, Any], key: str, default: int) -> int:
    try:
        value = int(params.get(key, default))
    except (TypeError, ValueError):
        value = int(default)
    return value


def _provider_values(providers: Dict[str, ProviderConfig], name: str) -> tuple[str, str]:
    provider_name = str(name or "").strip().lower()
    provider = providers.get(provider_name)
    api_key = str(provider.api_key if provider else "").strip()
    base_url = str(provider.base_url if provider else "").strip().rstrip("/")
    if not base_url:
        base_url = str(DEFAULT_PROVIDER_BASE_URLS.get(provider_name, "")).rstrip("/")
    return api_key, base_url


@dataclass(frozen=True)
class Settings:
    # Model config (local-only json)
    model_config_path: str
    llm_provider_pinned: bool
    llm_active_provider: str
    model_providers: Dict[str, ProviderConfig]
    model_routes: Dict[str, str]
    model_roles: Dict[str, Any]
    model_params: Dict[str, Any]
    model_context: Dict[str, Any]

    # Chat provider (OpenAI-compatible)
    chat_provider: str
    chat_api_key: SecretString
    chat_base_url: str

    # OpenRouter
    openrouter_api_key: SecretString
    openrouter_base_url: str

    # Moonshot (official OpenAI-compatible)
    moonshot_api_key: SecretString
    moonshot_base_url: str

    # Models
    main_model: str
    sub_model: str
    model_tier_map: Dict[str, str]

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
    lesson_plan_api_key: SecretString
    lesson_plan_base_url: str
    lesson_plan_model: str
    lesson_plan_subagent_concurrency: int

    # Model params
    main_model_temperature: float
    main_model_max_tokens: int
    sub_model_temperature: float
    sub_model_max_tokens: int

    # Study-materials reasoning defaults (Chat Completions `reasoning.effort`)
    study_materials_thinking_effort: str
    study_materials_thinking_model: str
    study_materials_writer_model: str

    # Optional overrides for lesson-plan style generation (fallback to MAIN_MODEL_* if unset)
    lesson_plan_temperature: float
    lesson_plan_max_tokens: int

    # Tool loop limits / timeouts
    max_tool_iterations: int
    api_timeout_seconds: int
    sub_ai_timeout_seconds: int
    llm_circuit_breaker_fail_threshold: int
    llm_circuit_breaker_open_seconds: int

    # Crawler defaults
    default_subject: str
    difficulty_query_mode: str

    # Reviewer (MCP tool)
    review_provider: str
    fireworks_api_key: SecretString
    fireworks_base_url: str
    review_model: str
    review_model_temperature: float
    review_model_max_tokens: int
    review_timeout_seconds: int
    review_max_stem_chars: int
    review_http_referer: str
    review_x_title: str

    # Zhipu BigModel (for MCP web-search tool)
    zhipu_api_key: SecretString
    zhipu_base_url: str
    zhipu_model: str
    zhipu_timeout_seconds: int

    # Metaso AI search (direct API; used by study-materials web_search_knowledge)
    metaso_api_key: SecretString
    metaso_base_url: str
    metaso_timeout_seconds: int

    # Tavily AI search (direct API; default search provider)
    tavily_api_key: SecretString
    tavily_base_url: str
    tavily_timeout_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        # Load from repo-root `.env` (if present) without overriding explicit env vars.
        #
        # External MCP clients often spawn the stdio server with an arbitrary CWD,
        # so relying on python-dotenv's default CWD search can miss the project's `.env`.
        repo_root = Path(__file__).resolve().parents[2]
        load_project_dotenv(override=False)

        model_json = load_model_json_config(repo_root=repo_root)
        model_config_path = str(model_json.path if model_json else resolve_model_config_path(repo_root=repo_root))
        model_providers = dict(model_json.providers if model_json else {})
        model_routes = dict(model_json.routes if model_json else {})
        model_roles = dict(model_json.models if model_json else {})
        model_params = dict(model_json.params if model_json else {})
        model_context = dict(model_json.context if model_json else {})

        llm_active_provider = str(model_json.active_provider if model_json else "openrouter").strip().lower()
        if llm_active_provider not in model_providers:
            llm_active_provider = next(iter(model_providers), llm_active_provider or "openrouter")
        llm_provider_pinned = bool(model_json.pinned) if model_json else True

        def _route_provider(route: str, fallback: str) -> str:
            candidate = str(model_routes.get(route) or fallback or "").strip().lower()
            return candidate if candidate in model_providers else str(fallback or "").strip().lower()

        chat_provider = _route_provider("chat", llm_active_provider)
        chat_api_key, chat_base_url = _provider_values(model_providers, chat_provider)
        lesson_plan_provider = _route_provider("lesson_plan", chat_provider)
        lesson_plan_api_key, lesson_plan_base_url = _provider_values(model_providers, lesson_plan_provider)
        review_provider = _route_provider("review", chat_provider)

        openrouter_api_key, base_url = _provider_values(model_providers, "openrouter")
        moonshot_api_key, moonshot_base_url = _provider_values(model_providers, "moonshot")
        fireworks_api_key, fireworks_base_url = _provider_values(model_providers, "fireworks")
        zhipu_api_key, zhipu_base_url = _provider_values(model_providers, "zhipu")
        metaso_base_url = _get_str("METASO_BASE_URL", "https://metaso.cn/api/v1").rstrip("/")
        tavily_base_url = _get_str("TAVILY_BASE_URL", "https://api.tavily.com").rstrip("/")

        metaso_api_key = _get_str("METASO_API_KEY", "")
        metaso_timeout_seconds = env_int("METASO_TIMEOUT", 30)
        tavily_api_key = _get_str("TAVILY_API_KEY", "")
        tavily_timeout_seconds = env_int("TAVILY_TIMEOUT", 60)
        main_model = _pick_provider_scoped(model_roles.get("main"), chat_provider) or "openai/gpt-5-mini"
        sub_model = _pick_provider_scoped(model_roles.get("sub"), chat_provider) or "openai/gpt-4o-mini"
        lesson_plan_model = (
            _pick_provider_scoped(model_roles.get("lesson_plan"), lesson_plan_provider) or main_model
        )
        lesson_plan_concurrency = env_int("LESSON_PLAN_SUBAGENT_CONCURRENCY", 3)

        study_materials_thinking_model_default = str(sub_model or lesson_plan_model or main_model).strip()
        study_materials_writer_model_default = str(main_model or lesson_plan_model or sub_model).strip()
        study_materials_thinking_model = (
            _pick_provider_scoped(model_roles.get("study_materials_thinking"), lesson_plan_provider)
            or study_materials_thinking_model_default
        )
        study_materials_writer_model = (
            _pick_provider_scoped(model_roles.get("study_materials_writer"), lesson_plan_provider)
            or study_materials_writer_model_default
        )
        deepthink_generator_model = (
            _pick_provider_scoped(model_roles.get("deepthink_generator"), chat_provider) or main_model
        )
        deepthink_evaluator_model = _pick_provider_scoped(model_roles.get("deepthink_evaluator"), chat_provider)
        review_model = (
            _pick_provider_scoped(model_roles.get("review"), review_provider)
            or main_model
        )

        model_tier_map = _normalize_model_tier_map(
            {
                "fast": sub_model,
                "cheap": sub_model,
                "main": main_model or lesson_plan_model,
                "heavy": review_model or deepthink_generator_model or main_model or lesson_plan_model,
            },
            model_params.get("model_tier_map") if isinstance(model_params.get("model_tier_map"), dict) else {},
        )

        deepthink_generator_temperature = _model_param_float(model_params, "deepthink_generator_temperature", 0.4)
        deepthink_generator_max_tokens = _model_param_int(model_params, "deepthink_generator_max_tokens", 1400)
        deepthink_evaluator_temperature = _model_param_float(model_params, "deepthink_evaluator_temperature", 0.2)
        deepthink_evaluator_max_tokens = _model_param_int(model_params, "deepthink_evaluator_max_tokens", 900)
        deepthink_reasoning_effort = str(model_params.get("deepthink_reasoning_effort") or "high").strip()

        tot_branch_factor = env_int("TOT_BRANCH_FACTOR", 3)
        tot_beam_width = env_int("TOT_BEAM_WIDTH", 3)
        tot_max_depth = env_int("TOT_MAX_DEPTH", 4)
        tot_prune_threshold = _get_float("TOT_PRUNE_THRESHOLD", 5.0)
        tot_timeout_seconds = env_int("TOT_TIMEOUT", 60)

        main_model_temperature = _model_param_float(model_params, "main_temperature", 0.7)
        main_model_max_tokens = _model_param_int(model_params, "main_max_tokens", 2000)
        sub_model_temperature = _model_param_float(model_params, "sub_temperature", 0.3)
        sub_model_max_tokens = _model_param_int(model_params, "sub_max_tokens", 1000)
        thinking_effort = str(
            model_params.get("study_materials_thinking_effort")
            or model_params.get("thinking_effort")
            or "xhigh"
        ).strip()

        return cls(
            model_config_path=model_config_path,
            llm_provider_pinned=llm_provider_pinned,
            llm_active_provider=llm_active_provider,
            model_providers=model_providers,
            model_routes=model_routes,
            model_roles=model_roles,
            model_params=model_params,
            model_context=model_context,
            chat_provider=chat_provider,
            chat_api_key=SecretString(chat_api_key),
            chat_base_url=chat_base_url,
            openrouter_api_key=SecretString(openrouter_api_key),
            openrouter_base_url=base_url,
            moonshot_api_key=SecretString(moonshot_api_key),
            moonshot_base_url=moonshot_base_url,
            main_model=main_model,
            # Use a cheaper/faster default for intermediate structured steps (summaries/outlines).
            sub_model=sub_model,
            model_tier_map=model_tier_map,
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
            lesson_plan_api_key=SecretString(lesson_plan_api_key),
            lesson_plan_base_url=lesson_plan_base_url,
            lesson_plan_model=lesson_plan_model,
            lesson_plan_subagent_concurrency=lesson_plan_concurrency,
            main_model_temperature=main_model_temperature,
            main_model_max_tokens=main_model_max_tokens,
            sub_model_temperature=sub_model_temperature,
            sub_model_max_tokens=sub_model_max_tokens,
            study_materials_thinking_effort=_normalize_reasoning_effort(thinking_effort, default="xhigh"),
            study_materials_thinking_model=study_materials_thinking_model,
            study_materials_writer_model=study_materials_writer_model,
            lesson_plan_temperature=_model_param_float(
                model_params,
                "lesson_plan_temperature",
                main_model_temperature,
            ),
            lesson_plan_max_tokens=_model_param_int(
                model_params,
                "lesson_plan_max_tokens",
                max(main_model_max_tokens, 50000),
            ),
            max_tool_iterations=env_int("MAX_TOOL_ITERATIONS", 10),
            api_timeout_seconds=env_int("API_TIMEOUT", 120),
            sub_ai_timeout_seconds=env_int("SUB_AI_TIMEOUT", 60),
            llm_circuit_breaker_fail_threshold=env_int("LLM_CIRCUIT_BREAKER_FAIL_THRESHOLD", 6),
            llm_circuit_breaker_open_seconds=env_int("LLM_CIRCUIT_BREAKER_OPEN_SECONDS", 30),
            default_subject=_get_str("DEFAULT_SUBJECT", "高中数学"),
            difficulty_query_mode=_get_str("DIFFICULTY_QUERY_MODE", "multi").lower(),
            review_provider=review_provider,
            fireworks_api_key=SecretString(fireworks_api_key),
            fireworks_base_url=fireworks_base_url,
            # Fireworks model IDs change over time; default to a currently listed, chat-capable model.
            review_model=review_model,
            review_model_temperature=_model_param_float(model_params, "review_temperature", 0.2),
            review_model_max_tokens=_model_param_int(model_params, "review_max_tokens", 1800),
            review_timeout_seconds=env_int("REVIEW_TIMEOUT", 90),
            review_max_stem_chars=env_int("REVIEW_MAX_STEM_CHARS", 900),
            review_http_referer=_get_str("REVIEW_HTTP_REFERER", "http://localhost:8000"),
            review_x_title=_get_str("REVIEW_X_TITLE", "Exam Paper Assistant - Reviewer"),
            zhipu_api_key=SecretString(zhipu_api_key),
            zhipu_base_url=zhipu_base_url,
            zhipu_model=_pick_provider_scoped(model_roles.get("zhipu_search"), "zhipu") or "glm-4.5",
            zhipu_timeout_seconds=env_int("ZHIPU_TIMEOUT", 60),
            metaso_api_key=SecretString(metaso_api_key),
            metaso_base_url=metaso_base_url,
            metaso_timeout_seconds=metaso_timeout_seconds,
            tavily_api_key=SecretString(tavily_api_key),
            tavily_base_url=tavily_base_url,
            tavily_timeout_seconds=tavily_timeout_seconds,
        )

    def summary(self) -> Dict[str, Any]:
        return {
            "model_config_path": self.model_config_path,
            "llm_provider_pinned": bool(self.llm_provider_pinned),
            "llm_active_provider": self.llm_active_provider,
            "chat_provider": self.chat_provider,
            "main_model": self.main_model,
            "sub_model": self.sub_model,
            "model_tier_map": self.model_tier_map,
            "lesson_plan_provider": self.lesson_plan_provider,
            "lesson_plan_model": self.lesson_plan_model,
            "study_materials_thinking_model": self.study_materials_thinking_model,
            "study_materials_writer_model": self.study_materials_writer_model,
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
            "tavily_configured": bool(self.tavily_api_key),
        }


settings = Settings.from_env()


def model_name(role: str, default: str = "", *, provider: str = "") -> str:
    """Resolve a named model role exclusively from the active model.json payload."""

    role_key = str(role or "").strip().lower().replace("-", "_")
    provider_name = str(provider or settings.lesson_plan_provider or settings.chat_provider or "").strip().lower()
    return _pick_provider_scoped(settings.model_roles.get(role_key), provider_name) or str(default or "").strip()


def model_param(name: str, default: Any = None) -> Any:
    """Read a generation/model parameter from model.json."""

    key = str(name or "").strip().lower().replace("-", "_")
    return settings.model_params.get(key, default)


def model_param_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    value = _model_param_int(settings.model_params, name, default)
    if minimum is not None:
        value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def model_param_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = _model_param_float(settings.model_params, name, default)
    if minimum is not None:
        value = max(float(minimum), value)
    if maximum is not None:
        value = min(float(maximum), value)
    return value


def model_param_bool(name: str, default: bool) -> bool:
    value = model_param(name, default)
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on"}


def model_context_value(name: str, default: Any = None) -> Any:
    key = str(name or "").strip().lower().replace("-", "_")
    return settings.model_context.get(key, default)


def model_provider(name: str = "") -> ProviderConfig:
    provider_name = str(name or settings.chat_provider or settings.llm_active_provider or "").strip().lower()
    configured = settings.model_providers.get(provider_name)
    if configured:
        return configured
    return ProviderConfig(
        name=provider_name,
        base_url=str(DEFAULT_PROVIDER_BASE_URLS.get(provider_name, "")),
        api_key="",
    )


def model_route(name: str, default: str = "") -> str:
    route = str(name or "").strip().lower().replace("-", "_")
    return str(settings.model_routes.get(route) or default or settings.llm_active_provider or "").strip().lower()

# Chat provider (OpenAI-compatible)
CHAT_PROVIDER = settings.chat_provider
CHAT_API_KEY = settings.chat_api_key.get_secret_value()
CHAT_BASE_URL = settings.chat_base_url

# Whether provider selection is pinned (explicit provider only) or inferred.
LLM_PROVIDER_PINNED = bool(settings.llm_provider_pinned)

# Back-compat module-level constants (used widely across the codebase).
OPENROUTER_API_KEY = settings.openrouter_api_key.get_secret_value()
OPENROUTER_BASE_URL = settings.openrouter_base_url

MOONSHOT_API_KEY = settings.moonshot_api_key.get_secret_value()
MOONSHOT_BASE_URL = settings.moonshot_base_url

MAIN_MODEL = settings.main_model
SUB_MODEL = settings.sub_model
MODEL_TIER_MAP = dict(settings.model_tier_map)

# Lesson plan / study-materials provider (OpenAI-compatible)
LESSON_PLAN_PROVIDER = settings.lesson_plan_provider
LESSON_PLAN_API_KEY = settings.lesson_plan_api_key.get_secret_value()
LESSON_PLAN_BASE_URL = settings.lesson_plan_base_url
LESSON_PLAN_MODEL = settings.lesson_plan_model
LESSON_PLAN_SUBAGENT_CONCURRENCY = settings.lesson_plan_subagent_concurrency

MAIN_MODEL_TEMPERATURE = settings.main_model_temperature
MAIN_MODEL_MAX_TOKENS = settings.main_model_max_tokens
SUB_MODEL_TEMPERATURE = settings.sub_model_temperature
SUB_MODEL_MAX_TOKENS = settings.sub_model_max_tokens

LESSON_PLAN_TEMPERATURE = settings.lesson_plan_temperature
LESSON_PLAN_MAX_TOKENS = settings.lesson_plan_max_tokens

STUDY_MATERIALS_THINKING_EFFORT_DEFAULT = settings.study_materials_thinking_effort
STUDY_MATERIALS_THINKING_MODEL = settings.study_materials_thinking_model
STUDY_MATERIALS_WRITER_MODEL = settings.study_materials_writer_model

MAX_TOOL_ITERATIONS = settings.max_tool_iterations
API_TIMEOUT = settings.api_timeout_seconds
SUB_AI_TIMEOUT = settings.sub_ai_timeout_seconds
LLM_CIRCUIT_BREAKER_FAIL_THRESHOLD = settings.llm_circuit_breaker_fail_threshold
LLM_CIRCUIT_BREAKER_OPEN_SECONDS = settings.llm_circuit_breaker_open_seconds

DEFAULT_SUBJECT = settings.default_subject
DIFFICULTY_QUERY_MODE = settings.difficulty_query_mode

# Reviewer settings (MCP tool)
REVIEW_PROVIDER = settings.review_provider
FIREWORKS_API_KEY = settings.fireworks_api_key.get_secret_value()
FIREWORKS_BASE_URL = settings.fireworks_base_url
REVIEW_MODEL = settings.review_model
REVIEW_MODEL_TEMPERATURE = settings.review_model_temperature
REVIEW_MODEL_MAX_TOKENS = settings.review_model_max_tokens
REVIEW_TIMEOUT = settings.review_timeout_seconds
REVIEW_MAX_STEM_CHARS = settings.review_max_stem_chars
REVIEW_HTTP_REFERER = settings.review_http_referer
REVIEW_X_TITLE = settings.review_x_title

# Zhipu BigModel settings (MCP web-search tool)
ZHIPU_API_KEY = settings.zhipu_api_key.get_secret_value()
ZHIPU_BASE_URL = settings.zhipu_base_url
ZHIPU_MODEL = settings.zhipu_model
ZHIPU_TIMEOUT = settings.zhipu_timeout_seconds

# Metaso AI search settings (direct API)
METASO_API_KEY = settings.metaso_api_key.get_secret_value()
METASO_BASE_URL = settings.metaso_base_url
METASO_TIMEOUT = settings.metaso_timeout_seconds

# Tavily AI search settings (direct API; default search provider)
TAVILY_API_KEY = settings.tavily_api_key.get_secret_value()
TAVILY_BASE_URL = settings.tavily_base_url
TAVILY_TIMEOUT = settings.tavily_timeout_seconds


def _runtime_value_map(next_settings: Settings) -> Dict[str, Any]:
    return {
        "CHAT_PROVIDER": next_settings.chat_provider,
        "CHAT_API_KEY": next_settings.chat_api_key.get_secret_value(),
        "CHAT_BASE_URL": next_settings.chat_base_url,
        "LLM_PROVIDER_PINNED": bool(next_settings.llm_provider_pinned),
        "OPENROUTER_API_KEY": next_settings.openrouter_api_key.get_secret_value(),
        "OPENROUTER_BASE_URL": next_settings.openrouter_base_url,
        "MOONSHOT_API_KEY": next_settings.moonshot_api_key.get_secret_value(),
        "MOONSHOT_BASE_URL": next_settings.moonshot_base_url,
        "MAIN_MODEL": next_settings.main_model,
        "SUB_MODEL": next_settings.sub_model,
        "MODEL_TIER_MAP": dict(next_settings.model_tier_map),
        "LESSON_PLAN_PROVIDER": next_settings.lesson_plan_provider,
        "LESSON_PLAN_API_KEY": next_settings.lesson_plan_api_key.get_secret_value(),
        "LESSON_PLAN_BASE_URL": next_settings.lesson_plan_base_url,
        "LESSON_PLAN_MODEL": next_settings.lesson_plan_model,
        "LESSON_PLAN_SUBAGENT_CONCURRENCY": next_settings.lesson_plan_subagent_concurrency,
        "MAIN_MODEL_TEMPERATURE": next_settings.main_model_temperature,
        "MAIN_MODEL_MAX_TOKENS": next_settings.main_model_max_tokens,
        "SUB_MODEL_TEMPERATURE": next_settings.sub_model_temperature,
        "SUB_MODEL_MAX_TOKENS": next_settings.sub_model_max_tokens,
        "LESSON_PLAN_TEMPERATURE": next_settings.lesson_plan_temperature,
        "LESSON_PLAN_MAX_TOKENS": next_settings.lesson_plan_max_tokens,
        "STUDY_MATERIALS_THINKING_EFFORT_DEFAULT": next_settings.study_materials_thinking_effort,
        "STUDY_MATERIALS_THINKING_MODEL": next_settings.study_materials_thinking_model,
        "STUDY_MATERIALS_WRITER_MODEL": next_settings.study_materials_writer_model,
        "MAX_TOOL_ITERATIONS": next_settings.max_tool_iterations,
        "API_TIMEOUT": next_settings.api_timeout_seconds,
        "SUB_AI_TIMEOUT": next_settings.sub_ai_timeout_seconds,
        "LLM_CIRCUIT_BREAKER_FAIL_THRESHOLD": next_settings.llm_circuit_breaker_fail_threshold,
        "LLM_CIRCUIT_BREAKER_OPEN_SECONDS": next_settings.llm_circuit_breaker_open_seconds,
        "DEFAULT_SUBJECT": next_settings.default_subject,
        "DIFFICULTY_QUERY_MODE": next_settings.difficulty_query_mode,
        "REVIEW_PROVIDER": next_settings.review_provider,
        "FIREWORKS_API_KEY": next_settings.fireworks_api_key.get_secret_value(),
        "FIREWORKS_BASE_URL": next_settings.fireworks_base_url,
        "REVIEW_MODEL": next_settings.review_model,
        "REVIEW_MODEL_TEMPERATURE": next_settings.review_model_temperature,
        "REVIEW_MODEL_MAX_TOKENS": next_settings.review_model_max_tokens,
        "REVIEW_TIMEOUT": next_settings.review_timeout_seconds,
        "REVIEW_MAX_STEM_CHARS": next_settings.review_max_stem_chars,
        "REVIEW_HTTP_REFERER": next_settings.review_http_referer,
        "REVIEW_X_TITLE": next_settings.review_x_title,
        "ZHIPU_API_KEY": next_settings.zhipu_api_key.get_secret_value(),
        "ZHIPU_BASE_URL": next_settings.zhipu_base_url,
        "ZHIPU_MODEL": next_settings.zhipu_model,
        "ZHIPU_TIMEOUT": next_settings.zhipu_timeout_seconds,
        "METASO_API_KEY": next_settings.metaso_api_key.get_secret_value(),
        "METASO_BASE_URL": next_settings.metaso_base_url,
        "METASO_TIMEOUT": next_settings.metaso_timeout_seconds,
        "TAVILY_API_KEY": next_settings.tavily_api_key.get_secret_value(),
        "TAVILY_BASE_URL": next_settings.tavily_base_url,
        "TAVILY_TIMEOUT": next_settings.tavily_timeout_seconds,
    }


def reload_settings_from_env() -> Settings:
    """Reload env/model config and refresh already imported backend setting constants best-effort."""

    global settings

    next_settings = Settings.from_env()
    values = _runtime_value_map(next_settings)

    settings = next_settings
    globals().update(values)

    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("backend."):
            continue
        for key, value in values.items():
            if hasattr(module, key):
                try:
                    setattr(module, key, value)
                except (AttributeError, TypeError):
                    pass

    return next_settings


def get_config_summary() -> Dict[str, Any]:
    """Compatibility wrapper for older callers."""
    return settings.summary()
