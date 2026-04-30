from __future__ import annotations

import inspect
import json
import re
from typing import Any, Dict, List

from backend.core.settings import STUDY_MATERIALS_THINKING_EFFORT_DEFAULT
from backend.llm.client import chat_completion, chat_completion_text
from backend.mcp.tools.python_scientific_compute import openai_tool_spec as scientific_compute_tool_spec
from backend.mcp.tools.python_scientific_compute import python_scientific_compute
from backend.question_library.gen_utils import (
    ReasoningEventHandler,
    _format_generation_tool_call_log,
    _format_generation_tool_result_log,
)


async def _emit_reasoning_event(
    on_reasoning_event: ReasoningEventHandler,
    *,
    event_type: str,
    stage_id: str,
    stage_label: str,
    source: str = "",
    content: str = "",
    mode: str = "",
    message: str = "",
) -> None:
    if on_reasoning_event is None:
        return

    payload = {
        "type": str(event_type or "").strip() or "reasoning_delta",
        "stage_id": str(stage_id or "").strip(),
        "stage_label": str(stage_label or "").strip(),
    }
    if source:
        payload["source"] = str(source or "").strip()
    if content:
        payload["content"] = str(content or "").strip()
    if mode:
        payload["mode"] = str(mode or "").strip()
    if message:
        payload["message"] = str(message or "").strip()

    try:
        result = on_reasoning_event(payload)
        if inspect.isawaitable(result):
            await result
    except Exception:
        return


async def _chat_json_with_reasoning(
    *,
    messages: List[Dict[str, Any]],
    model: str,
    temperature: float,
    max_tokens: int,
    req_id_prefix: str,
    retries: int,
    raise_on_fail: bool,
    stage_id: str,
    stage_label: str,
    stream_reasoning: bool,
    on_reasoning_event: ReasoningEventHandler,
) -> str:
    emitted_chars = 0
    reasoning_effort = str(STUDY_MATERIALS_THINKING_EFFORT_DEFAULT or "").strip() or "medium"
    working_messages: List[Dict[str, Any]] = [dict(message) for message in messages]

    async def _on_reasoning_delta(chunk: str) -> None:
        nonlocal emitted_chars
        text = str(chunk or "")
        if not text.strip():
            return
        emitted_chars += len(text)
        await _emit_reasoning_event(
            on_reasoning_event,
            event_type="reasoning_delta",
            stage_id=stage_id,
            stage_label=stage_label,
            source="raw",
            content=text,
        )

    if stream_reasoning:
        await _emit_reasoning_event(
            on_reasoning_event,
            event_type="reasoning_status",
            stage_id=stage_id,
            stage_label=stage_label,
            mode="raw",
            message="尝试透传模型原始 reasoning。",
        )

    tool_mode_failed = False
    for _ in range(4):
        try:
            res = await chat_completion(
                messages=working_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                reasoning={"effort": reasoning_effort, "exclude": not bool(stream_reasoning)},
                tools=[scientific_compute_tool_spec()],
                tool_choice="auto",
                stream=bool(stream_reasoning),
                on_reasoning_delta=_on_reasoning_delta if stream_reasoning else None,
                raise_on_fail=raise_on_fail,
                retries=retries,
                req_id_prefix=req_id_prefix,
            )
        except Exception as exc:
            tool_mode_failed = True
            await _emit_reasoning_event(
                on_reasoning_event,
                event_type="reasoning_status",
                stage_id=stage_id,
                stage_label=stage_label,
                mode="trace",
                message=f"科学计算工具接线失败，已回退普通生成: {str(exc or '').strip()[:220]}",
            )
            break

        tool_calls = list(res.tool_calls or [])
        if not tool_calls:
            text = str(res.content or "")
            break

        working_messages.append({"role": "assistant", "content": res.content or "", "tool_calls": tool_calls})
        for tc in tool_calls[:3]:
            fn = tc.get("function") if isinstance(tc, dict) else {}
            tool_name = str((fn or {}).get("name") or "").strip() or "unknown_tool"
            raw_args = (fn or {}).get("arguments") if isinstance(fn, dict) else {}
            tool_call_id = str(tc.get("id") or "").strip()
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except Exception:
                    arguments = {}
            else:
                arguments = raw_args if isinstance(raw_args, dict) else {}

            await _emit_reasoning_event(
                on_reasoning_event,
                event_type="reasoning_status",
                stage_id=stage_id,
                stage_label=stage_label,
                mode="trace",
                message=_format_generation_tool_call_log(tool_name, arguments),
            )

            if tool_name == "python_scientific_compute":
                tool_result = await python_scientific_compute(
                    code=str(arguments.get("code") or "").strip(),
                    purpose=str(arguments.get("purpose") or "").strip(),
                    timeout_seconds=int(arguments.get("timeout_seconds") or 5),
                )
            else:
                tool_result = {"success": False, "error": f"unsupported_tool: {tool_name}"}

            await _emit_reasoning_event(
                on_reasoning_event,
                event_type="reasoning_status",
                stage_id=stage_id,
                stage_label=stage_label,
                mode="trace",
                message=_format_generation_tool_result_log(tool_name, tool_result),
            )

            tool_payload = json.dumps(tool_result, ensure_ascii=False)
            if tool_call_id:
                working_messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": tool_payload})
            else:
                working_messages.append({"role": "tool", "content": tool_payload})
    else:
        tool_mode_failed = True
        await _emit_reasoning_event(
            on_reasoning_event,
            event_type="reasoning_status",
            stage_id=stage_id,
            stage_label=stage_label,
            mode="trace",
            message="科学计算工具调用轮次达到上限，已回退普通生成。",
        )
        text = ""

    if tool_mode_failed or not str(locals().get("text", "") or "").strip():
        text = await chat_completion_text(
            messages=working_messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            reasoning={"effort": reasoning_effort, "exclude": not bool(stream_reasoning)},
            stream=bool(stream_reasoning),
            on_reasoning_delta=_on_reasoning_delta if stream_reasoning else None,
            raise_on_fail=raise_on_fail,
            retries=retries,
            req_id_prefix=req_id_prefix,
        )

    if stream_reasoning and emitted_chars <= 0:
        await _emit_reasoning_event(
            on_reasoning_event,
            event_type="reasoning_status",
            stage_id=stage_id,
            stage_label=stage_label,
            mode="trace",
            message="当前模型未返回原始 reasoning，已降级为事件级 trace。",
        )
        await _emit_reasoning_event(
            on_reasoning_event,
            event_type="reasoning_delta",
            stage_id=stage_id,
            stage_label=stage_label,
            source="trace",
            content=f"{stage_label} 已完成一次模型调用。",
        )
    return text


def _extract_json_obj(text: str) -> Dict[str, Any]:
    value = _extract_json_value(text)
    return value if isinstance(value, dict) else {}


def _strip_json_fence(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\\s*", "", raw).lstrip()
        raw = re.sub(r"\\s*```$", "", raw).rstrip()
    return raw


def _repair_json_backslashes(raw: str) -> str:
    """
    Best-effort repair for "almost JSON" emitted by some models when LaTeX is embedded
    in JSON strings (e.g. `\\( ... \\)` is output without JSON escaping).
    """

    s = str(raw or "")
    if not s:
        return s

    out: list[str] = []
    in_str = False
    i = 0
    hex_chars = set("0123456789abcdefABCDEF")

    while i < len(s):
        ch = s[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue

        if ch == '"':
            out.append(ch)
            in_str = False
            i += 1
            continue

        if ch != "\\":
            out.append(ch)
            i += 1
            continue

        if i + 1 >= len(s):
            out.append("\\\\")
            i += 1
            continue

        nxt = s[i + 1]

        if nxt in {'"', "\\", "/"}:
            out.append("\\")
            out.append(nxt)
            i += 2
            continue

        if nxt in {"b", "f", "n", "r", "t"}:
            after = s[i + 2] if (i + 2) < len(s) else ""
            if after.isascii() and after.isalpha():
                out.append("\\\\")
                out.append(nxt)
                i += 2
                continue
            out.append("\\")
            out.append(nxt)
            i += 2
            continue

        if nxt == "u":
            if (i + 5) < len(s):
                hex4 = s[i + 2 : i + 6]
                if len(hex4) == 4 and all(c in hex_chars for c in hex4):
                    out.append("\\")
                    out.append("u")
                    out.append(hex4)
                    i += 6
                    continue
            out.append("\\\\")
            out.append("u")
            i += 2
            continue

        out.append("\\\\")
        i += 1

    return "".join(out)


def _extract_json_value(text: str) -> Any:
    raw = _strip_json_fence(text)
    if not raw:
        return {}

    for candidate in (raw, raw[raw.find("{") : raw.rfind("}") + 1], raw[raw.find("[") : raw.rfind("]") + 1]):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        try:
            repaired = _repair_json_backslashes(candidate)
            if repaired != candidate:
                return json.loads(repaired)
        except Exception:
            continue
    return {}
