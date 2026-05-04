from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.llm import console as llm_console
from backend.llm.reasoning_extract import extract_reasoning_chunk
from backend.llm.response_handlers import retry_after
from backend.llm.result import ChatCompletionResult, elapsed_s
from backend.llm.sse_parser import finalize_tool_call_chunks, merge_tool_call_chunks, usage_cached_tokens
from backend.llm.transport import client_stream

logger = get_logger(__name__)


async def _emit(buf: str, callback: Optional[Callable[[str], Awaitable[None]]]) -> None:
    if buf and callback is not None:
        try:
            await callback(buf)
        except Exception:
            logger.exception("llm_delta_callback_failed")
            return


async def read_stream_response(
    *,
    resp: Any,
    req_id: str,
    provider: str,
    model: str,
    emit_chars: int,
    emit_interval_s: float,
    on_reasoning_delta: Optional[Callable[[str], Awaitable[None]]],
    on_content_delta: Optional[Callable[[str], Awaitable[None]]],
) -> ChatCompletionResult:
    content_parts: List[str] = []
    finish_reason = ""
    usage: Dict[str, Any] = {}
    tool_call_chunks: Dict[int, Dict[str, Any]] = {}
    reasoning_buf = ""
    loop = asyncio.get_running_loop()
    last_emit_t = loop.time()
    async for line in resp.aiter_lines():
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw:
            continue
        if raw == "[DONE]":
            break
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        choices = obj.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        choice0 = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}
        message = choice0.get("message") if isinstance(choice0.get("message"), dict) else {}
        reasoning_chunk = extract_reasoning_chunk(choice0=choice0, delta=delta, message=message)
        if reasoning_chunk:
            reasoning_buf += reasoning_chunk
            now_t = loop.time()
            if len(reasoning_buf) >= emit_chars or (now_t - last_emit_t) >= emit_interval_s:
                await _emit(reasoning_buf, on_reasoning_delta)
                llm_console.log_delta(req_id=req_id, channel="reasoning", text=reasoning_buf)
                reasoning_buf, last_emit_t = "", now_t
        content_chunk = delta.get("content")
        if isinstance(content_chunk, str) and content_chunk:
            content_parts.append(content_chunk)
            llm_console.log_delta(req_id=req_id, channel="content", text=content_chunk)
            await _emit(content_chunk, on_content_delta)
        tc_raw = delta.get("tool_calls") if isinstance(delta.get("tool_calls"), list) else message.get("tool_calls")
        if isinstance(tc_raw, list) and tc_raw:
            merge_tool_call_chunks(tool_call_chunks, tc_raw)
        finish_reason = str(choice0.get("finish_reason") or finish_reason)
        if isinstance(obj.get("usage"), dict):
            usage = dict(obj.get("usage") or {})
    if reasoning_buf:
        await _emit(reasoning_buf, on_reasoning_delta)
        llm_console.log_delta(req_id=req_id, channel="reasoning", text=reasoning_buf)
    return ChatCompletionResult(
        content="".join(content_parts),
        finish_reason=finish_reason,
        usage=usage,
        tool_calls=finalize_tool_call_chunks(tool_call_chunks),
        cached_tokens=usage_cached_tokens(usage),
    )


async def request_stream(**kwargs: Any) -> Optional[ChatCompletionResult]:
    async with client_stream(
        kwargs["client"],
        "POST",
        kwargs["url"],
        headers=kwargs["headers"],
        payload=kwargs["payload"],
        timeout_s=kwargs["timeout_s"],
    ) as resp:
        if resp.status_code in kwargs["retry_statuses"] and kwargs["attempt"] < kwargs["max_retries"] - 1:
            error = f"http_status_{resp.status_code}"
            llm_console.log_end(req_id=kwargs["req_id"], elapsed_s=elapsed_s(kwargs["start_ts"]), error=error)
            await asyncio.sleep(retry_after(resp, kwargs["attempt"]))
            return None
        if resp.status_code != 200:
            try:
                await resp.aread()
            except Exception:
                logger.exception(
                    "llm_response_drain_failed",
                    extra={"status": int(getattr(resp, "status_code", 0) or 0)},
                )
        resp.raise_for_status()
        result = await read_stream_response(
            resp=resp,
            req_id=kwargs["req_id"],
            provider=kwargs["provider"],
            model=kwargs["model"],
            emit_chars=kwargs["emit_chars"],
            emit_interval_s=kwargs["emit_interval_s"],
            on_reasoning_delta=kwargs["on_reasoning_delta"],
            on_content_delta=kwargs["on_content_delta"],
        )
        llm_console.log_end(
            req_id=kwargs["req_id"],
            elapsed_s=elapsed_s(kwargs["start_ts"]),
            finish_reason=result.finish_reason,
            usage=result.usage,
            content_chars=len(result.content),
        )
        return result
