from __future__ import annotations

from typing import Any, Dict, List


def coerce_reasoning_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "reasoning_content", "summary"):
            v = value.get(key)
            if isinstance(v, str) and v:
                return str(v)
        parts = value.get("parts")
        if isinstance(parts, list) and parts:
            out_parts: List[str] = []
            for item in parts:
                text = coerce_reasoning_text(item)
                if text:
                    out_parts.append(text)
            return "".join(out_parts)
        return ""
    if isinstance(value, list):
        out_parts = []
        for item in value:
            text = coerce_reasoning_text(item)
            if text:
                out_parts.append(text)
        return "".join(out_parts)
    return ""


def _coerce_reasoning_details(details: Any) -> str:
    if not (isinstance(details, list) and details):
        return coerce_reasoning_text(details)

    text_parts: List[str] = []
    summary_parts: List[str] = []
    for item in details:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("text"), str) and item.get("text"):
            text_parts.append(str(item.get("text") or ""))
        elif isinstance(item.get("summary"), str) and item.get("summary"):
            summary_parts.append(str(item.get("summary") or ""))
    if text_parts:
        return "".join(text_parts)
    if summary_parts:
        return "".join(summary_parts)
    return ""


def extract_reasoning_chunk(
    *,
    choice0: Dict[str, Any],
    delta: Dict[str, Any],
    message: Dict[str, Any],
) -> str:
    r_chunk = _coerce_reasoning_details(delta.get("reasoning_details"))
    if not r_chunk:
        r_chunk = coerce_reasoning_text(delta.get("reasoning_content"))
    if not r_chunk:
        r_chunk = coerce_reasoning_text(delta.get("reasoning"))
    if not r_chunk:
        r_chunk = coerce_reasoning_text(message.get("reasoning_details"))
    if not r_chunk:
        r_chunk = coerce_reasoning_text(message.get("reasoning_content"))
    if not r_chunk:
        r_chunk = coerce_reasoning_text(message.get("reasoning"))
    if not r_chunk:
        r_chunk = coerce_reasoning_text(choice0.get("reasoning_details"))
    if not r_chunk:
        r_chunk = coerce_reasoning_text(choice0.get("reasoning_content"))
    if not r_chunk:
        r_chunk = coerce_reasoning_text(choice0.get("reasoning"))
    return r_chunk
