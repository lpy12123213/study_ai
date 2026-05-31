from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from backend.llm.client import ChatCompletionResult, chat_completion
from backend.llm.json_utils import JsonParseMode, extract_json_value
from backend.llm.result import mark_message_cacheable


def _coerce_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = int(default)
    return max(int(minimum), min(int(parsed), int(maximum)))


def _coerce_float(
    value: Any,
    default: Optional[float],
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return default
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        parsed = max(float(minimum), parsed)
    if maximum is not None:
        parsed = min(float(maximum), parsed)
    return parsed


def _first_env_value(names: Sequence[str]) -> Optional[str]:
    for name in names:
        value = os.getenv(str(name or "").strip())
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _mark_system_messages_cacheable(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for message in messages:
        item = dict(message or {})
        role = str(item.get("role") or "").strip().lower()
        if role == "system" and "cache_control" not in item:
            item = mark_message_cacheable(item)
        out.append(item)
    return out


def resolve_retries(
    retries: Optional[int],
    *,
    env_vars: Sequence[str] = (),
    default: int = 3,
    minimum: int = 1,
    maximum: int = 10,
) -> int:
    raw: Any = retries
    if raw is None:
        raw = _first_env_value(env_vars)
    if raw is None:
        raw = default
    return _coerce_int(raw, default, minimum=minimum, maximum=maximum)


def resolve_timeout_s(
    timeout_s: Optional[float],
    *,
    env_vars: Sequence[str] = (),
    default: Optional[float] = None,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> Optional[float]:
    raw: Any = timeout_s
    if raw is None:
        raw = _first_env_value(env_vars)
    return _coerce_float(raw, default, minimum=minimum, maximum=maximum)


async def run_tool_use(
    *,
    messages: List[Dict[str, Any]],
    model: str,
    temperature: float,
    max_tokens: int,
    response_format: Optional[Dict[str, Any]] = None,
    reasoning: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    stream: bool = False,
    on_reasoning_delta: Optional[Callable[[str], Awaitable[None]]] = None,
    on_content_delta: Optional[Callable[[str], Awaitable[None]]] = None,
    reasoning_emit_chars: int = 240,
    reasoning_emit_interval_s: float = 0.25,
    raise_on_fail: bool = True,
    retries: Optional[int] = None,
    retry_env_vars: Sequence[str] = (),
    default_retries: int = 3,
    max_retries: int = 10,
    timeout_s: Optional[float] = None,
    timeout_env_vars: Sequence[str] = (),
    default_timeout_s: Optional[float] = None,
    min_timeout_s: Optional[float] = None,
    max_timeout_s: Optional[float] = None,
    req_id_prefix: str = "llm",
    scope: str = "lesson_plan",
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    moonshot_key: Optional[str] = None,
    moonshot_base_url: Optional[str] = None,
) -> ChatCompletionResult:
    return await chat_completion(
        messages=_mark_system_messages_cacheable(messages),
        model=str(model or "").strip(),
        temperature=float(temperature),
        max_tokens=int(max_tokens),
        response_format=response_format,
        reasoning=reasoning,
        tools=tools,
        tool_choice=tool_choice,
        stream=bool(stream),
        on_reasoning_delta=on_reasoning_delta,
        on_content_delta=on_content_delta,
        reasoning_emit_chars=int(reasoning_emit_chars),
        reasoning_emit_interval_s=float(reasoning_emit_interval_s),
        raise_on_fail=bool(raise_on_fail),
        retries=resolve_retries(
            retries,
            env_vars=retry_env_vars,
            default=default_retries,
            maximum=max_retries,
        ),
        timeout_s=resolve_timeout_s(
            timeout_s,
            env_vars=timeout_env_vars,
            default=default_timeout_s,
            minimum=min_timeout_s,
            maximum=max_timeout_s,
        ),
        req_id_prefix=str(req_id_prefix or "llm"),
        scope=str(scope or "lesson_plan"),
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        moonshot_key=moonshot_key,
        moonshot_base_url=moonshot_base_url,
    )


async def run_text(
    *,
    messages: List[Dict[str, Any]],
    model: str,
    temperature: float,
    max_tokens: int,
    response_format: Optional[Dict[str, Any]] = None,
    reasoning: Optional[Dict[str, Any]] = None,
    stream: bool = False,
    on_reasoning_delta: Optional[Callable[[str], Awaitable[None]]] = None,
    on_content_delta: Optional[Callable[[str], Awaitable[None]]] = None,
    reasoning_emit_chars: int = 240,
    reasoning_emit_interval_s: float = 0.25,
    raise_on_fail: bool = True,
    retries: Optional[int] = None,
    retry_env_vars: Sequence[str] = (),
    default_retries: int = 3,
    max_retries: int = 10,
    timeout_s: Optional[float] = None,
    timeout_env_vars: Sequence[str] = (),
    default_timeout_s: Optional[float] = None,
    min_timeout_s: Optional[float] = None,
    max_timeout_s: Optional[float] = None,
    req_id_prefix: str = "llm",
    scope: str = "lesson_plan",
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    moonshot_key: Optional[str] = None,
    moonshot_base_url: Optional[str] = None,
) -> str:
    res = await run_tool_use(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        reasoning=reasoning,
        stream=stream,
        on_reasoning_delta=on_reasoning_delta,
        on_content_delta=on_content_delta,
        reasoning_emit_chars=reasoning_emit_chars,
        reasoning_emit_interval_s=reasoning_emit_interval_s,
        raise_on_fail=raise_on_fail,
        retries=retries,
        retry_env_vars=retry_env_vars,
        default_retries=default_retries,
        max_retries=max_retries,
        timeout_s=timeout_s,
        timeout_env_vars=timeout_env_vars,
        default_timeout_s=default_timeout_s,
        min_timeout_s=min_timeout_s,
        max_timeout_s=max_timeout_s,
        req_id_prefix=req_id_prefix,
        scope=scope,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        moonshot_key=moonshot_key,
        moonshot_base_url=moonshot_base_url,
    )
    return str(res.content or "")


async def run_json(
    *,
    messages: List[Dict[str, Any]],
    model: str,
    temperature: float,
    max_tokens: int,
    response_format: Optional[Dict[str, Any]] = None,
    default: Any = None,
    parse_mode: JsonParseMode = "lenient",
    **kwargs: Any,
) -> Any:
    text = await run_text(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format or {"type": "json_object"},
        **kwargs,
    )
    fallback = {} if default is None else default
    return extract_json_value(text, default=fallback, mode=parse_mode)
