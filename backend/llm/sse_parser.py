from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple


def tool_call_index(chunk: Dict[str, Any], fallback: int) -> int:
    try:
        idx = int(chunk.get("index"))
        return idx if idx >= 0 else fallback
    except (TypeError, ValueError):
        return fallback


def merge_tool_call_chunks(target: Dict[int, Dict[str, Any]], chunks: Any) -> None:
    if not isinstance(chunks, list):
        return
    for fallback_idx, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            continue
        idx = tool_call_index(chunk, fallback_idx)
        cur = target.setdefault(idx, {"type": "function", "function": {"name": "", "arguments": ""}})

        call_id = str(chunk.get("id") or "").strip()
        if call_id:
            cur["id"] = call_id

        call_type = str(chunk.get("type") or "").strip()
        if call_type:
            cur["type"] = call_type

        fn = chunk.get("function") if isinstance(chunk.get("function"), dict) else {}
        if not fn:
            continue
        cur_fn = cur.setdefault("function", {})

        name = str(fn.get("name") or "").strip()
        if name:
            cur_fn["name"] = name

        args = fn.get("arguments")
        if isinstance(args, str) and args:
            cur_fn["arguments"] = str(cur_fn.get("arguments") or "") + args


def finalize_tool_call_chunks(target: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx in sorted(target):
        call = target[idx]
        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
        if not str(fn.get("name") or "").strip() and not str(fn.get("arguments") or "").strip():
            continue
        if not str(call.get("id") or "").strip():
            call["id"] = f"call_{idx}"
        if not str(call.get("type") or "").strip():
            call["type"] = "function"
        out.append(dict(call))
    return out


def parse_sse_chat_response(raw_text: str) -> Optional[Dict[str, Any]]:
    raw = str(raw_text or "")
    if "data:" not in raw:
        return None

    content_parts: List[str] = []
    finish_reason = ""
    usage: Dict[str, Any] = {}
    tool_call_chunks: Dict[int, Dict[str, Any]] = {}
    saw_chunk = False

    for line in raw.splitlines():
        chunk = str(line or "").strip()
        if not chunk or chunk.startswith(":") or not chunk.startswith("data:"):
            continue
        data = chunk[5:].strip()
        if not data:
            continue
        if data == "[DONE]":
            saw_chunk = True
            break
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        saw_chunk = True
        choices = obj.get("choices")
        if not isinstance(choices, list) or not choices:
            if isinstance(obj.get("usage"), dict):
                usage = dict(obj.get("usage") or {})
            continue
        choice0 = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}
        message = choice0.get("message") if isinstance(choice0.get("message"), dict) else {}

        c_chunk = delta.get("content")
        if isinstance(c_chunk, str) and c_chunk:
            content_parts.append(c_chunk)
        elif isinstance(message.get("content"), str) and message.get("content"):
            content_parts.append(str(message.get("content") or ""))

        tc_raw = delta.get("tool_calls")
        if not isinstance(tc_raw, list):
            tc_raw = message.get("tool_calls")
        if isinstance(tc_raw, list) and tc_raw:
            merge_tool_call_chunks(tool_call_chunks, tc_raw)

        fr_chunk = choice0.get("finish_reason")
        if isinstance(fr_chunk, str) and fr_chunk:
            finish_reason = fr_chunk

        if isinstance(obj.get("usage"), dict):
            usage = dict(obj.get("usage") or {})

    if not saw_chunk:
        return None

    message: Dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
    tool_calls = finalize_tool_call_chunks(tool_call_chunks)
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": usage,
    }


def usage_cached_tokens(usage: Dict[str, Any]) -> int:
    if not isinstance(usage, dict):
        return 0
    candidates: List[Any] = [
        usage.get("cached_tokens"),
        usage.get("cache_read_input_tokens"),
        usage.get("cache_creation_input_tokens"),
    ]
    for nested_key in ("prompt_tokens_details", "input_tokens_details"):
        nested = usage.get(nested_key)
        if isinstance(nested, dict):
            candidates.extend([nested.get("cached_tokens"), nested.get("cache_read"), nested.get("cache_read_input_tokens")])
    for value in candidates:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0


def decode_chat_response_payload(resp: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        data = resp.json()
        return (dict(data), "") if isinstance(data, dict) else ({}, "")
    except ValueError as exc:
        parse_error = str(exc or "").strip() or "invalid_json_response"
    try:
        raw_text = str(resp.text or "")
    except AttributeError:
        raw_text = ""
    sse_data = parse_sse_chat_response(raw_text)
    if isinstance(sse_data, dict):
        return sse_data, ""
    if not raw_text.strip():
        return None, "empty_response_body"
    raw_lower = raw_text.lstrip().lower()
    if raw_lower.startswith("<!doctype html") or raw_lower.startswith("<html"):
        return None, "html_response_body"
    try:
        data = json.loads(raw_text)
        return (dict(data), "") if isinstance(data, dict) else ({}, "")
    except json.JSONDecodeError as exc:
        parse_error = str(exc or "").strip() or parse_error
    return None, parse_error
