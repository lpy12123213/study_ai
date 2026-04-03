"""LLM module (public API).

This package is imported widely across the backend (agent/chat/question_library/mcp/lesson_plan...).
We keep `__init__` *import-light* to avoid circular imports, but still provide a convenient
public API surface.

Prefer explicit imports when touching internals, for example:
- `backend.llm.client` for core OpenAI-compatible chat completions
- `backend.llm.model_config` for provider config (`config/model.json`)
- `backend.llm.console` for debug logging helpers
- `backend.llm.providers` for provider/model normalization helpers

For consumers, these names are re-exported lazily:
- `chat_completion`, `chat_completion_text`, `is_llm_configured`, `ChatCompletionResult`, ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    # submodules
    "client",
    "console",
    "model_config",
    "providers",
    # client public API (lazy)
    "ChatCompletionResult",
    "chat_completion",
    "chat_completion_text",
    "get_llm_api_key_override",
    "get_moonshot_api_key_override",
    "is_llm_configured",
    "reset_llm_api_key_override",
    "reset_moonshot_api_key_override",
    "set_llm_api_key_override",
    "set_moonshot_api_key_override",
]


if TYPE_CHECKING:
    from backend.llm.client import (  # noqa: F401
        ChatCompletionResult,
        chat_completion,
        chat_completion_text,
        get_llm_api_key_override,
        get_moonshot_api_key_override,
        is_llm_configured,
        reset_llm_api_key_override,
        reset_moonshot_api_key_override,
        set_llm_api_key_override,
        set_moonshot_api_key_override,
    )


_LAZY_CLIENT_EXPORTS = {
    "ChatCompletionResult",
    "chat_completion",
    "chat_completion_text",
    "get_llm_api_key_override",
    "get_moonshot_api_key_override",
    "is_llm_configured",
    "reset_llm_api_key_override",
    "reset_moonshot_api_key_override",
    "set_llm_api_key_override",
    "set_moonshot_api_key_override",
}


def __getattr__(name: str) -> Any:  # noqa: ANN401
    if name in _LAZY_CLIENT_EXPORTS:
        from backend.llm import client as _client

        return getattr(_client, name)
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | _LAZY_CLIENT_EXPORTS)
