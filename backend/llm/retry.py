from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

from backend.core.logging_utils import get_logger
from backend.core.record_replay import RecordReplayStore, record_enabled, replay_enabled
from backend.core.settings import API_TIMEOUT
from backend.llm import console as llm_console
from backend.llm.circuit_breaker import circuit_is_open, circuit_key, circuit_record_failure, circuit_record_success
from backend.llm.model_limits import maybe_append_v1_base_url
from backend.llm.providers import RESPONSES_PROTOCOL, resolve_protocol
from backend.llm.request_setup import build_payload, record_replay_request, request_headers, resolve_request_config
from backend.llm.response_handlers import drop_optional_fields, handle_http_status, parse_response, retry_after
from backend.llm.result import (
    ChatCompletionResult,
    elapsed_s,
    empty_llm_result,
    llm_error_code,
    record_metric,
    record_payload,
    record_replay_response,
)
from backend.llm.sse_parser import decode_chat_response_payload
from backend.llm.streaming import request_stream
from backend.llm.transport import client_get, client_post, get_shared_llm_http_client

logger = get_logger(__name__)


def _request_timeout_s(timeout_s: Optional[float]) -> Optional[float]:
    """Resolve the per-request timeout; an explicit non-positive value disables it."""

    if timeout_s is not None:
        try:
            explicit = float(timeout_s)
        except (TypeError, ValueError):
            explicit = float(API_TIMEOUT or 120)
        if explicit <= 0:
            return None
        return max(1.0, min(explicit, 600.0))
    return max(1.0, min(float(API_TIMEOUT or 120), 600.0))


async def chat_completion(
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
    retries: int = 3,
    timeout_s: Optional[float] = None,
    req_id_prefix: str = "llm",
    scope: str = "lesson_plan",
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    moonshot_key: Optional[str] = None,
    moonshot_base_url: Optional[str] = None,
    httpx_factory: Any = None,
    provider_resolver: Any = None,
) -> ChatCompletionResult:
    resolved_provider, resolved_base_url, resolved_api_key, resolved_model, temp = resolve_request_config(
        scope=scope,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        moonshot_key=moonshot_key,
        moonshot_base_url=moonshot_base_url,
        model=model,
        temperature=temperature,
        provider_resolver=provider_resolver,
    )
    protocol = resolve_protocol(provider=resolved_provider, model=resolved_model)
    rr_store = RecordReplayStore("llm")
    rr_request = record_replay_request(
        provider=resolved_provider, base_url=resolved_base_url, model=resolved_model, messages=messages,
        temperature=temp, max_tokens=max_tokens, response_format=response_format, reasoning=reasoning,
        tools=tools, tool_choice=tool_choice, stream=stream,
        protocol=protocol,
    )
    if replay_enabled():
        fixture, key = rr_store.load(request=rr_request)
        resp = fixture.get("response") if isinstance(fixture, dict) else None
        if isinstance(resp, dict):
            return record_replay_response(resp, provider=resolved_provider, model=resolved_model, stream=bool(stream))
        if not record_enabled():
            if raise_on_fail:
                raise RuntimeError(f"replay_fixture_missing key={key}")
            return empty_llm_result("replay_fixture_missing")
    if not resolved_api_key:
        if raise_on_fail:
            raise RuntimeError("llm_not_configured")
        return empty_llm_result("llm_not_configured")

    req_id_base = f"{req_id_prefix}-{uuid.uuid4().hex[:8]}"
    request_timeout_s = _request_timeout_s(timeout_s)
    retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
    max_retries, last_error = max(1, min(int(retries or 3), 10)), ""
    cb_key = circuit_key(provider=resolved_provider, model=resolved_model)
    cb_open, cb_wait = circuit_is_open(cb_key)
    if cb_open:
        last_error = f"llm_circuit_open wait_s={cb_wait:.1f}"
        llm_console.log_end(req_id=f"{req_id_base}-cb", elapsed_s=0.0, error=last_error)
        if raise_on_fail:
            raise RuntimeError("llm_circuit_open")
        return empty_llm_result("llm_circuit_open")

    payload = await build_payload(
        provider=resolved_provider,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        model=resolved_model,
        messages=messages,
        temperature=temp,
        max_tokens=int(max_tokens),
        response_format=response_format,
        reasoning=reasoning,
        tools=tools,
        tool_choice=tool_choice,
        stream=stream,
        get_client=lambda: get_shared_llm_http_client(httpx_factory),
        client_get=client_get,
        protocol=protocol,
    )
    headers = request_headers(resolved_provider, resolved_api_key)
    dropped_reasoning = dropped_response_format = retried_with_v1 = False
    # Tracks (status, api_msg) signatures of permanent 4xx errors seen by this call so
    # handle_http_status can fail fast when the identical error survives a mutation.
    permanent_signatures: set = set()
    emit_chars = max(1, int(reasoning_emit_chars or 240))
    emit_interval_s = max(0.05, min(float(reasoning_emit_interval_s or 0.25), 2.0))
    request_base_url = str(resolved_base_url or "").strip().rstrip("/")

    attempt = 0
    request_count = 0
    adaptive_retries_left = 5
    while attempt < max_retries and request_count < max_retries + 5:
        request_count += 1
        endpoint = "responses" if protocol == RESPONSES_PROTOCOL else "chat/completions"
        req_id, url = f"{req_id_base}-{request_count}", f"{request_base_url}/{endpoint}"
        start_ts = llm_console.log_start(
            req_id=req_id, provider=resolved_provider, model=resolved_model, stream=bool(payload.get("stream")),
            temperature=float(payload.get("temperature") or 0.0),
            max_tokens=int(payload.get("max_tokens") or payload.get("max_output_tokens") or 0),
            base_url=request_base_url,
        )
        try:
            client = await get_shared_llm_http_client(httpx_factory)
            if bool(payload.get("stream")):
                result = await request_stream(
                    client=client, url=url, headers=headers, payload=payload, timeout_s=request_timeout_s,
                    retry_statuses=retry_statuses, attempt=attempt, max_retries=max_retries, req_id=req_id,
                    start_ts=start_ts, provider=resolved_provider, model=resolved_model, emit_chars=emit_chars,
                    emit_interval_s=emit_interval_s, on_reasoning_delta=on_reasoning_delta,
                    on_content_delta=on_content_delta,
                    protocol=protocol,
                )
                if result is None:
                    attempt += 1
                    continue
                if record_enabled():
                    rr_store.save(request=rr_request, response=record_payload(result))
                circuit_record_success(cb_key)
                return record_metric(result, provider=resolved_provider, model=resolved_model, stream=True,
                                     elapsed_s=elapsed_s(start_ts), request_id=req_id)

            resp = await client_post(client, url, headers=headers, payload=payload, timeout_s=request_timeout_s)
            if resp.status_code in retry_statuses and attempt < max_retries - 1:
                last_error = f"http_status_{resp.status_code}"
                llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=last_error)
                await asyncio.sleep(retry_after(resp, attempt))
                attempt += 1
                continue
            resp.raise_for_status()
            data, decode_error = decode_chat_response_payload(resp)
            if data is None:
                last_error = decode_error or "invalid_json_response"
                v1_url = maybe_append_v1_base_url(request_base_url)
                if v1_url and adaptive_retries_left > 0 and not retried_with_v1 and v1_url != request_base_url and last_error in {"empty_response_body", "html_response_body", "Expecting value: line 1 column 1 (char 0)"}:
                    logger.warning("llm_retry_with_v1_base_url", extra={"req_id": req_id, "model": resolved_model, "provider": resolved_provider, "base_url": request_base_url, "retry_base_url": v1_url, "error": last_error})
                    request_base_url, retried_with_v1 = v1_url, True
                    adaptive_retries_left -= 1
                    llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(0.2)
                    continue
                dropped_response_format, dropped_reasoning, dropped = drop_optional_fields(payload, dropped_response_format, dropped_reasoning)
                if dropped and adaptive_retries_left > 0:
                    adaptive_retries_left -= 1
                    llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(0.2)
                    continue
                if attempt < max_retries - 1:
                    llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(min(3.0, 0.4 + random.random() * 0.8))
                    attempt += 1
                    continue
                if raise_on_fail:
                    raise RuntimeError(f"llm_request_failed model={resolved_model} err={last_error}")
                circuit_record_failure(cb_key)
                return empty_llm_result(last_error)
            if protocol == RESPONSES_PROTOCOL and isinstance(data.get("error"), dict):
                error = data.get("error") or {}
                raise RuntimeError(
                    "llm_response_failed:"
                    + str(error.get("code") or error.get("message") or "unknown").strip()
                )
            result, retry_without_reasoning = parse_response(
                data,
                payload,
                dropped_reasoning,
                protocol=protocol,
            )
            if protocol == RESPONSES_PROTOCOL and result.error_code:
                raise RuntimeError(f"llm_response_failed:{result.error_code}")
            if retry_without_reasoning:
                dropped_reasoning, last_error = True, "empty_content_drop_reasoning"
                logger.warning("llm_empty_content_drop_reasoning", extra={"req_id": req_id, "model": resolved_model, "provider": resolved_provider, "base_url": request_base_url})
                llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=last_error)
                if adaptive_retries_left > 0 and request_count < max_retries + 5:
                    adaptive_retries_left -= 1
                    await asyncio.sleep(0.2)
                    continue
                if raise_on_fail:
                    raise RuntimeError(f"llm_request_failed model={resolved_model} err={last_error}")
                circuit_record_failure(cb_key)
                return empty_llm_result(last_error)
            if result.content:
                llm_console.log_delta(req_id=req_id, channel="content", text=result.content)
            llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), finish_reason=result.finish_reason, usage=result.usage, content_chars=len(result.content))
            if record_enabled():
                rr_store.save(request=rr_request, response=record_payload(result))
            circuit_record_success(cb_key)
            return record_metric(result, provider=resolved_provider, model=resolved_model, stream=False,
                                 elapsed_s=elapsed_s(start_ts), request_id=req_id)
        except asyncio.CancelledError:
            raise
        except httpx.HTTPStatusError as exc:
            handled = await handle_http_status(
                exc=exc, payload=payload, messages=messages, provider=resolved_provider, model=resolved_model,
                request_base_url=request_base_url, retried_with_v1=retried_with_v1,
                dropped_response_format=dropped_response_format, dropped_reasoning=dropped_reasoning,
                attempt=attempt, max_retries=max_retries, req_id=req_id, start_ts=start_ts,
                retry_statuses=retry_statuses, permanent_signatures=permanent_signatures,
            )
            if handled["retry"]:
                if int(getattr(exc.response, "status_code", 0) or 0) in retry_statuses:
                    attempt += 1
                elif adaptive_retries_left > 0:
                    adaptive_retries_left -= 1
                request_base_url = handled.get("request_base_url", request_base_url)
                retried_with_v1 = bool(handled.get("retried_with_v1", retried_with_v1))
                dropped_response_format = bool(handled.get("dropped_response_format", dropped_response_format))
                dropped_reasoning = bool(handled.get("dropped_reasoning", dropped_reasoning))
                continue
            if raise_on_fail:
                raise RuntimeError(f"llm_request_failed status={handled.get('status')} model={resolved_model} provider={resolved_provider} msg={handled.get('api_msg') or handled.get('last_error')}")
            circuit_record_failure(cb_key)
            return empty_llm_result(str(handled.get("api_msg") or handled.get("last_error") or ""), status=int(handled.get("status") or 0))
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            last_error = str(exc)
            llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=last_error)
            if attempt < max_retries - 1:
                await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                attempt += 1
                continue
            if raise_on_fail:
                raise RuntimeError(f"llm_request_failed model={resolved_model} err={last_error}")
            circuit_record_failure(cb_key)
            return empty_llm_result(last_error, exc=exc)
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)
            llm_console.log_end(req_id=req_id, elapsed_s=elapsed_s(start_ts), error=last_error)
            if attempt < max_retries - 1:
                await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                attempt += 1
                continue
            if raise_on_fail:
                raise RuntimeError(f"llm_request_failed model={resolved_model} err={last_error}")
            circuit_record_failure(cb_key)
            return empty_llm_result(last_error, exc=exc)
    logger.warning("llm request failed after retries", extra={"error": last_error, "error_code": llm_error_code(last_error), "model": resolved_model})
    if raise_on_fail:
        raise RuntimeError(f"llm_request_failed model={resolved_model} err={last_error or 'unknown'}")
    circuit_record_failure(cb_key)
    return empty_llm_result(last_error or "unknown")
