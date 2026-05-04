from __future__ import annotations

from typing import Any

import httpx

from backend.core.settings import CHAT_API_KEY, LESSON_PLAN_API_KEY, MOONSHOT_API_KEY
from backend.llm.key_override import (
    get_llm_api_key_override,
    get_moonshot_api_key_override,
    reset_llm_api_key_override,
    reset_moonshot_api_key_override,
    set_llm_api_key_override,
    set_moonshot_api_key_override,
)
from backend.llm.model_limits import (
    _OPENROUTER_CACHE_FILE as _OPENROUTER_CACHE_FILE,
)
from backend.llm.model_limits import (
    cap_max_tokens,
    cap_max_tokens_for_messages,
)
from backend.llm.providers import resolve_provider
from backend.llm.result import (
    ChatCompletionResult,
    cache_control_ephemeral,
    cacheable_message,
    mark_message_cacheable,
)
from backend.llm.result import (
    resp_error as _resp_error,
)
from backend.llm.retry import chat_completion as _chat_completion
from backend.llm.sse_parser import (
    decode_chat_response_payload as _decode_chat_response_payload,
)
from backend.llm.sse_parser import (
    parse_sse_chat_response as _parse_sse_chat_response,
)
from backend.llm.tokenizer import (
    estimate_messages_tokens as _estimate_messages_tokens,
)
from backend.llm.tokenizer import (
    tokenizer_backend,
)
from backend.llm.transport import (
    close_shared_llm_http_client as _close_shared_llm_http_client,
)
from backend.llm.transport import (
    get_shared_llm_http_client as _get_shared_llm_http_client,
)


async def get_shared_llm_http_client():
    return await _get_shared_llm_http_client(httpx.AsyncClient)


async def close_shared_llm_http_client() -> None:
    await _close_shared_llm_http_client()


async def chat_completion(**kwargs: Any) -> ChatCompletionResult:
    kwargs.setdefault("httpx_factory", httpx.AsyncClient)
    kwargs.setdefault("provider_resolver", resolve_provider)
    return await _chat_completion(**kwargs)


async def chat_completion_text(**kwargs: Any) -> str:
    kwargs.setdefault("raise_on_fail", False)
    result = await chat_completion(**kwargs)
    return str(result.content or "")


def is_llm_configured(*, scope: str = "lesson_plan") -> bool:
    scope_in = str(scope or "").strip().lower()
    if scope_in in {"chat", "main"}:
        return bool(
            get_llm_api_key_override()
            or get_moonshot_api_key_override()
            or str(CHAT_API_KEY or "").strip()
            or str(MOONSHOT_API_KEY or "").strip()
        )
    if scope_in in {"any", "all", "*"}:
        return bool(
            get_llm_api_key_override()
            or get_moonshot_api_key_override()
            or str(CHAT_API_KEY or "").strip()
            or str(LESSON_PLAN_API_KEY or "").strip()
            or str(MOONSHOT_API_KEY or "").strip()
        )
    return bool(
        get_llm_api_key_override()
        or get_moonshot_api_key_override()
        or str(LESSON_PLAN_API_KEY or "").strip()
        or str(MOONSHOT_API_KEY or "").strip()
    )


__all__ = [
    "ChatCompletionResult",
    "_OPENROUTER_CACHE_FILE",
    "_decode_chat_response_payload",
    "_estimate_messages_tokens",
    "_parse_sse_chat_response",
    "_resp_error",
    "cache_control_ephemeral",
    "cacheable_message",
    "cap_max_tokens",
    "cap_max_tokens_for_messages",
    "chat_completion",
    "chat_completion_text",
    "close_shared_llm_http_client",
    "get_llm_api_key_override",
    "get_moonshot_api_key_override",
    "get_shared_llm_http_client",
    "is_llm_configured",
    "mark_message_cacheable",
    "reset_llm_api_key_override",
    "reset_moonshot_api_key_override",
    "set_llm_api_key_override",
    "set_moonshot_api_key_override",
    "tokenizer_backend",
]
