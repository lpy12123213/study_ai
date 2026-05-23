from __future__ import annotations

import asyncio
from typing import Any, Dict

from backend.llm import console as llm_console
from backend.llm.model_limits import (
    context_input_multiplier,
    context_reserve_tokens,
    maybe_append_v1_base_url,
    parse_context_len_error,
)
from backend.llm.result import ChatCompletionResult, elapsed_s, resp_error
from backend.llm.retry_policy import DEFAULT_RETRY_POLICY
from backend.llm.sse_parser import usage_cached_tokens
from backend.llm.tokenizer import estimate_messages_tokens


def retry_after(resp: Any, attempt: int) -> float:
    return DEFAULT_RETRY_POLICY.http_retry_delay(resp, attempt=attempt)


def parse_response(data: Dict[str, Any], payload: Dict[str, Any], dropped_reasoning: bool) -> tuple[ChatCompletionResult, bool]:
    try:
        choice0 = data.get("choices", [{}])[0] if isinstance(data, dict) else {}
        message0 = choice0.get("message", {}) if isinstance(choice0, dict) else {}
        raw_tool_calls = message0.get("tool_calls")
        tool_calls = list(raw_tool_calls) if isinstance(raw_tool_calls, list) else []
        content = str(message0.get("content") or "").strip()
        usage = dict(data.get("usage") or {}) if isinstance(data, dict) and isinstance(data.get("usage"), dict) else {}
        finish_reason = str(choice0.get("finish_reason") or "") if isinstance(choice0, dict) else ""
    except (AttributeError, IndexError, TypeError, ValueError):
        raise RuntimeError("invalid_response")
    if not content and not tool_calls and not dropped_reasoning and "reasoning" in payload:
        payload.pop("reasoning", None)
        return ChatCompletionResult(), True
    return (
        ChatCompletionResult(
            content=content,
            finish_reason=finish_reason,
            usage=usage,
            tool_calls=tool_calls,
            cached_tokens=usage_cached_tokens(usage),
        ),
        False,
    )


def drop_optional_fields(payload: Dict[str, Any], dropped_response_format: bool, dropped_reasoning: bool) -> tuple[bool, bool, bool]:
    dropped = False
    if "response_format" in payload and not dropped_response_format:
        payload.pop("response_format", None)
        dropped_response_format = dropped = True
    if "reasoning" in payload and not dropped_reasoning:
        payload.pop("reasoning", None)
        dropped_reasoning = dropped = True
    if "tool_choice" in payload:
        # Some models (e.g. deepseek-reasoner) don't support tool_choice
        payload.pop("tool_choice", None)
        dropped = True
    return dropped_response_format, dropped_reasoning, dropped


async def handle_http_status(**kwargs: Any) -> Dict[str, Any]:
    exc = kwargs["exc"]
    status = exc.response.status_code if exc.response is not None else 0
    api_msg = resp_error(exc.response)
    last_error = f"http_status_{status}"
    req_id, start_ts = kwargs["req_id"], kwargs["start_ts"]
    base_url, model, provider = kwargs["request_base_url"], kwargs["model"], kwargs["provider"]
    v1_url = maybe_append_v1_base_url(base_url)
    if status in {404, 405} and v1_url and not kwargs["retried_with_v1"] and v1_url != base_url:
        llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=api_msg or last_error)
        await asyncio.sleep(DEFAULT_RETRY_POLICY.adaptation_delay())
        return {"retry": True, "request_base_url": v1_url, "retried_with_v1": True}
    if status in {400, 422}:
        limit, input_tokens, _ = parse_context_len_error(api_msg)
        if limit > 0:
            input_tokens = input_tokens or int(estimate_messages_tokens(kwargs["messages"]) * context_input_multiplier())
            allowed = int(limit - input_tokens - context_reserve_tokens(limit))
            try:
                current = int(kwargs["payload"].get("max_tokens") or 0)
            except (AttributeError, TypeError, ValueError):
                current = 0
            if allowed > 0 and current > allowed:
                kwargs["payload"]["max_tokens"] = int(allowed)
                llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=api_msg or last_error)
                await asyncio.sleep(DEFAULT_RETRY_POLICY.adaptation_delay())
                return {"retry": True}
        if provider == "moonshot" and "temperature" in (api_msg or "").lower() and "only 1" in (api_msg or "").lower():
            kwargs["payload"]["temperature"] = 1.0
            llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=api_msg or last_error)
            await asyncio.sleep(DEFAULT_RETRY_POLICY.adaptation_delay())
            return {"retry": True}
        drf, dr, dropped = drop_optional_fields(
            kwargs["payload"], kwargs["dropped_response_format"], kwargs["dropped_reasoning"]
        )
        if dropped:
            llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=last_error)
            await asyncio.sleep(DEFAULT_RETRY_POLICY.adaptation_delay())
            return {"retry": True, "dropped_response_format": drf, "dropped_reasoning": dr}
    if status in kwargs["retry_statuses"] and kwargs["attempt"] < kwargs["max_retries"] - 1:
        llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=last_error)
        await asyncio.sleep(DEFAULT_RETRY_POLICY.retryable_status_delay(attempt=kwargs["attempt"]))
        return {"retry": True}
    llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=api_msg or last_error)
    return {"retry": False, "status": status, "api_msg": api_msg, "last_error": last_error, "model": model}
