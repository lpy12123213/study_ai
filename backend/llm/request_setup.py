from __future__ import annotations

from typing import Any, Dict, List

from backend.core.settings import LLM_PROVIDER_PINNED, REVIEW_HTTP_REFERER, REVIEW_X_TITLE
from backend.llm.key_override import resolve_api_key, resolve_moonshot_base_url, resolve_moonshot_key, scope_defaults
from backend.llm.model_limits import cap_max_tokens, cap_max_tokens_for_messages, openrouter_model_limits
from backend.llm.providers import resolve_provider


def resolve_request_config(
    *,
    scope: str,
    provider: str | None,
    base_url: str | None,
    api_key: str | None,
    moonshot_key: str | None,
    moonshot_base_url: str | None,
    model: str,
    temperature: float,
    provider_resolver: Any = None,
) -> tuple[str, str, str, str, float]:
    defaults = scope_defaults(scope)
    resolver = provider_resolver or resolve_provider
    resolved_provider, resolved_base_url, resolved_api_key, resolved_model = resolver(
        provider=str(provider or defaults.provider or "").strip().lower() or "openrouter",
        base_url=str(base_url or defaults.base_url or "").strip().rstrip("/"),
        api_key=resolve_api_key(api_key, defaults.api_key),
        model=str(model or "").strip(),
        moonshot_key=resolve_moonshot_key(moonshot_key),
        moonshot_base_url=resolve_moonshot_base_url(moonshot_base_url),
        allow_moonshot_auto_switch=not bool(LLM_PROVIDER_PINNED),
    )
    temp = 1.0 if resolved_provider == "moonshot" and resolved_model.lower().startswith("kimi-") else float(temperature)
    return resolved_provider, resolved_base_url, resolved_api_key, resolved_model, temp


def request_headers(provider: str, api_key: str) -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        if str(REVIEW_HTTP_REFERER or "").strip():
            headers["HTTP-Referer"] = str(REVIEW_HTTP_REFERER or "").strip()
        if str(REVIEW_X_TITLE or "").strip():
            headers["X-Title"] = str(REVIEW_X_TITLE or "").strip()
    return headers


def record_replay_request(
    *,
    provider: str,
    base_url: str,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
    response_format: Dict[str, Any] | None,
    reasoning: Dict[str, Any] | None,
    tools: List[Dict[str, Any]] | None,
    tool_choice: Any,
    stream: bool,
) -> Dict[str, Any]:
    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": int(max_tokens),
        "response_format": response_format or None,
        "reasoning": reasoning or None,
        "tools": tools or None,
        "tool_choice": tool_choice or None,
        "stream": bool(stream),
    }


async def payload_max_tokens(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    requested_max_tokens: int,
    get_client: Any,
    client_get: Any,
) -> int:
    if requested_max_tokens <= 0:
        return 0
    capped = 0
    if provider == "openrouter":
        ctx_len, max_comp = await openrouter_model_limits(
            base_url=base_url,
            api_key=api_key,
            model=model,
            get_client=get_client,
            client_get=client_get,
        )
        if ctx_len > 0:
            capped = cap_max_tokens(
                messages=messages,
                context_length=ctx_len,
                requested_max_tokens=requested_max_tokens,
                max_completion_tokens=max_comp,
            )
    return int(capped or cap_max_tokens_for_messages(messages=messages, model=model, requested_max_tokens=requested_max_tokens))


async def build_payload(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
    response_format: Dict[str, Any] | None,
    reasoning: Dict[str, Any] | None,
    tools: List[Dict[str, Any]] | None,
    tool_choice: Any,
    stream: bool,
    get_client: Any,
    client_get: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature, "stream": False}
    payload_max = await payload_max_tokens(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        requested_max_tokens=int(max_tokens),
        get_client=get_client,
        client_get=client_get,
    )
    if payload_max > 0:
        payload["max_tokens"] = payload_max
    if isinstance(response_format, dict) and response_format:
        payload["response_format"] = dict(response_format)
    if isinstance(tools, list) and tools:
        payload["tools"] = list(tools)
        # DeepSeek reasoner models don't support tool_choice parameter.
        # This includes deepseek-reasoner, deepseek-r1*, and deepseek-v4-flash (which is a reasoner variant).
        effective_tool_choice = tool_choice if tool_choice is not None else "auto"
        model_lower = (model or "").lower()
        is_deepseek_reasoner = provider == "deepseek" and (
            "reasoner" in model_lower
            or model_lower.startswith("deepseek-r1")
            or "v4" in model_lower
        )
        if not is_deepseek_reasoner:
            payload["tool_choice"] = effective_tool_choice
    if stream and provider in {"openrouter", "moonshot", "ikuncode"}:
        payload["stream"] = True
    if isinstance(reasoning, dict) and reasoning and not (provider == "openrouter" and not stream and model.lower().startswith("deepseek/")):
        payload["reasoning"] = dict(reasoning)
    return payload
