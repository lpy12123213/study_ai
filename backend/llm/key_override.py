from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional

from backend.core.settings import (
    CHAT_API_KEY,
    CHAT_BASE_URL,
    CHAT_PROVIDER,
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_PROVIDER,
    MOONSHOT_API_KEY,
    MOONSHOT_BASE_URL,
)


@dataclass(frozen=True)
class ScopeDefaults:
    provider: str
    base_url: str
    api_key: str


# Per-request LLM key overrides (e.g. provided by the frontend settings page).
# These values must stay in-memory only.
_llm_api_key_override_var: ContextVar[str] = ContextVar("llm_api_key_override", default="")
_moonshot_api_key_override_var: ContextVar[str] = ContextVar("moonshot_api_key_override", default="")


def set_llm_api_key_override(api_key: Optional[str]) -> Token:
    return _llm_api_key_override_var.set(str(api_key or "").strip())


def reset_llm_api_key_override(token: Token) -> None:
    _llm_api_key_override_var.reset(token)


def get_llm_api_key_override() -> str:
    return str(_llm_api_key_override_var.get() or "").strip()


def set_moonshot_api_key_override(api_key: Optional[str]) -> Token:
    return _moonshot_api_key_override_var.set(str(api_key or "").strip())


def reset_moonshot_api_key_override(token: Token) -> None:
    _moonshot_api_key_override_var.reset(token)


def get_moonshot_api_key_override() -> str:
    return str(_moonshot_api_key_override_var.get() or "").strip()


def scope_defaults(scope: str = "lesson_plan") -> ScopeDefaults:
    scope_in = str(scope or "").strip().lower()
    if scope_in in {"chat", "main"}:
        return ScopeDefaults(
            provider=str(CHAT_PROVIDER or ""),
            base_url=str(CHAT_BASE_URL or ""),
            api_key=str(CHAT_API_KEY or ""),
        )
    return ScopeDefaults(
        provider=str(LESSON_PLAN_PROVIDER or ""),
        base_url=str(LESSON_PLAN_BASE_URL or ""),
        api_key=str(LESSON_PLAN_API_KEY or ""),
    )


def resolve_api_key(api_key: Optional[str], default_api_key: str) -> str:
    return str(api_key or "").strip() or get_llm_api_key_override() or str(default_api_key or "").strip()


def resolve_moonshot_key(moonshot_key: Optional[str]) -> str:
    return str(moonshot_key or "").strip() or get_moonshot_api_key_override() or str(MOONSHOT_API_KEY or "").strip()


def resolve_moonshot_base_url(moonshot_base_url: Optional[str]) -> str:
    return str(moonshot_base_url or MOONSHOT_BASE_URL or "").strip().rstrip("/")


def is_llm_configured(*, scope: str = "lesson_plan") -> bool:
    scope_in = str(scope or "").strip().lower()
    llm_override = get_llm_api_key_override()
    moonshot_override = get_moonshot_api_key_override()
    if scope_in in {"chat", "main"}:
        return bool(llm_override or moonshot_override or str(CHAT_API_KEY or "").strip() or str(MOONSHOT_API_KEY or ""))
    if scope_in in {"any", "all", "*"}:
        return bool(
            llm_override
            or moonshot_override
            or str(CHAT_API_KEY or "").strip()
            or str(LESSON_PLAN_API_KEY or "").strip()
            or str(MOONSHOT_API_KEY or "").strip()
        )
    return bool(llm_override or moonshot_override or str(LESSON_PLAN_API_KEY or "").strip() or str(MOONSHOT_API_KEY or ""))
