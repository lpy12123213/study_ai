from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from backend.llm import metrics as llm_metrics
from backend.llm.sse_parser import usage_cached_tokens


@dataclass
class ChatCompletionResult:
    content: str = ""
    finish_reason: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    error_code: str = ""
    cached_tokens: int = 0


def elapsed_s(start_ts: float) -> float:
    try:
        return max(0.0, time.time() - float(start_ts)) if start_ts else 0.0
    except (TypeError, ValueError):
        return 0.0


def resp_error(resp: Optional[httpx.Response]) -> str:
    if resp is None:
        return ""
    msg = ""
    try:
        data = resp.json()
        if isinstance(data, dict):
            err = data.get("error")
            msg = (
                str(err.get("message") or err.get("detail") or err.get("error") or "").strip()
                if isinstance(err, dict)
                else str(err or "").strip()
            )
            msg = msg or str(data.get("message") or data.get("detail") or "").strip()
    except ValueError:
        msg = ""
    if not msg:
        try:
            msg = str(resp.text or "").strip()
        except httpx.HTTPError:
            msg = ""
    return msg.replace("\n", " ").strip()[:260] if msg else ""


def llm_error_code(error: str = "", *, status: int = 0, exc: Optional[BaseException] = None) -> str:
    raw = str(error or "").strip().lower()
    if isinstance(exc, httpx.TimeoutException) or "timeout" in raw:
        return "timeout"
    if isinstance(exc, httpx.RequestError):
        return "network"
    if status:
        return "4xx" if 400 <= status < 500 else "5xx" if status >= 500 else "http"
    if raw.startswith("http_status_"):
        try:
            return llm_error_code(status=int(raw.rsplit("_", 1)[-1]))
        except (TypeError, ValueError):
            return "http"
    if "empty_content" in raw or "empty response" in raw:
        return "empty_content"
    if "invalid_json" in raw or "invalid_response" in raw or "response_body" in raw or "expecting value" in raw:
        return "parse"
    if raw in {"llm_not_configured", "not_configured"}:
        return "not_configured"
    return "circuit_open" if "circuit" in raw else "unknown"


def empty_llm_result(error: str = "", *, status: int = 0, exc: Optional[BaseException] = None) -> ChatCompletionResult:
    return ChatCompletionResult(error_code=llm_error_code(error, status=status, exc=exc))


def cache_control_ephemeral() -> Dict[str, str]:
    return {"type": "ephemeral"}


def mark_message_cacheable(message: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(message or {})
    out["cache_control"] = cache_control_ephemeral()
    return out


def cacheable_message(role: str, content: Any) -> Dict[str, Any]:
    return mark_message_cacheable({"role": role, "content": content})


def record_payload(result: ChatCompletionResult) -> Dict[str, Any]:
    return {
        "content": result.content,
        "finish_reason": result.finish_reason,
        "usage": result.usage,
        "tool_calls": result.tool_calls,
        "error_code": result.error_code,
        "cached_tokens": result.cached_tokens,
    }


def record_replay_response(resp: Dict[str, Any], *, provider: str, model: str, stream: bool) -> ChatCompletionResult:
    usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
    result = ChatCompletionResult(
        content=str(resp.get("content") or ""),
        finish_reason=str(resp.get("finish_reason") or ""),
        usage=dict(usage),
        tool_calls=list(resp.get("tool_calls") or []) if isinstance(resp.get("tool_calls"), list) else [],
        error_code=str(resp.get("error_code") or ""),
        cached_tokens=int(resp.get("cached_tokens") or usage_cached_tokens(dict(usage))),
    )
    llm_metrics.record_llm_call(
        provider=provider,
        model=model,
        usage=result.usage,
        mode="replay",
        stream=stream,
        finish_reason=result.finish_reason,
    )
    return result


def record_metric(
    result: ChatCompletionResult,
    *,
    provider: str,
    model: str,
    stream: bool,
    elapsed_s: float,
    request_id: str,
) -> ChatCompletionResult:
    llm_metrics.record_llm_call(
        provider=provider,
        model=model,
        usage=result.usage,
        stream=stream,
        elapsed_s=elapsed_s,
        finish_reason=result.finish_reason,
        request_id=request_id,
    )
    return result
