from __future__ import annotations

import inspect
import json
import time
from typing import Any, Dict, List

from backend.core.logging_utils import get_logger
from backend.core.settings import STUDY_MATERIALS_THINKING_EFFORT_DEFAULT, model_role_binding
from backend.generation.question_library.evolution import (
    ARBITER_ROLE,
    GENERATOR_CALL_OUTPUT_TOKEN_LIMIT,
    GENERATOR_ROLE,
    OPENCODE_GO_PROVIDER,
    SUPERVISOR_CALL_OUTPUT_TOKEN_LIMIT,
    SUPERVISOR_ROLE,
    current_trace,
    sanitize_messages_for_role,
)
from backend.generation.question_library.gen_utils import (
    ReasoningEventHandler,
    _format_generation_tool_call_log,
    _format_generation_tool_result_log,
)
from backend.integrations.mcp.tools.python_scientific_compute import python_scientific_compute
from backend.llm.json_utils import strip_code_fences
from backend.llm.runner import run_text, run_tool_use

chat_completion = run_tool_use
chat_completion_text = run_text
logger = get_logger(__name__)


def _bounded_role_max_tokens(role: str, requested: int, *, unbounded: bool = False) -> int:
    if unbounded:
        return 0
    cap = (
        GENERATOR_CALL_OUTPUT_TOKEN_LIMIT
        if str(role or "").strip() == GENERATOR_ROLE
        else SUPERVISOR_CALL_OUTPUT_TOKEN_LIMIT
    )
    try:
        value = int(requested or 0)
    except (TypeError, ValueError):
        value = 0
    return cap if value <= 0 else min(value, cap)


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
        logger.warning("question_generation_reasoning_event_failed", exc_info=True)
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
    role: str = "",
) -> str:
    emitted_chars = 0
    reasoning_effort = str(STUDY_MATERIALS_THINKING_EFFORT_DEFAULT or "").strip() or "medium"
    role_name = str(role or "").strip()
    if not role_name:
        if str(req_id_prefix or "").startswith("ql_arbiter"):
            role_name = ARBITER_ROLE
        elif str(req_id_prefix or "").startswith(
            ("ql_judge", "ql_solve", "ql_amb", "ql_distill", "ql_curriculum", "ql_ref")
        ):
            role_name = SUPERVISOR_ROLE
        else:
            role_name = GENERATOR_ROLE
    binding = model_role_binding(role_name, required_provider=OPENCODE_GO_PROVIDER)
    working_messages = sanitize_messages_for_role(messages, role=role_name)
    model = binding.model
    trace = current_trace()
    unbounded_live_test = bool(trace is not None and trace.unbounded_live_test)
    effective_max_tokens = _bounded_role_max_tokens(
        role_name,
        max_tokens,
        unbounded=unbounded_live_test,
    )
    effective_timeout_s = 0.0 if unbounded_live_test else None
    # A traced question-generation request is the unit counted by the hard
    # Muse/DeepSeek budgets. Keep transport retries at one so a logical call
    # cannot silently expand into several billable HTTP requests.
    effective_retries = 1 if trace is not None else retries

    def _record_call(res: Any, started_at: float) -> None:
        if trace is None:
            return
        trace.record_call(
            role=role_name,
            model=binding.model,
            protocol="responses" if role_name == GENERATOR_ROLE else "chat_completions",
            usage=dict(getattr(res, "usage", {}) or {}),
            elapsed_s=time.monotonic() - started_at,
        )

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
            if trace is not None:
                trace.reserve_call(role_name)
            call_started_at = time.monotonic()
            res = await chat_completion(
                messages=working_messages,
                model=model,
                temperature=temperature,
                max_tokens=effective_max_tokens,
                response_format={"type": "json_object"},
                reasoning={"effort": reasoning_effort, "exclude": not bool(stream_reasoning)},
                tools=None,
                tool_choice=None,
                stream=bool(stream_reasoning),
                on_reasoning_delta=_on_reasoning_delta if stream_reasoning else None,
                raise_on_fail=True,
                retries=effective_retries,
                req_id_prefix=req_id_prefix,
                provider=binding.provider,
                base_url=binding.base_url,
                api_key=binding.api_key,
                timeout_s=effective_timeout_s,
            )
            _record_call(res, call_started_at)
        except RuntimeError as exc:
            if trace is not None:
                trace.record_failure(role=role_name, error=str(exc), fatal=False)
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
        except Exception as exc:
            if trace is not None:
                trace.record_failure(role=role_name, error=str(exc), fatal=False)
            logger.warning("question_generation_tool_mode_failed", exc_info=True)
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
                except (json.JSONDecodeError, TypeError):
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
        if trace is not None:
            trace.reserve_call(role_name)
        call_started_at = time.monotonic()
        try:
            text = await chat_completion_text(
                messages=working_messages,
                model=model,
                temperature=temperature,
                max_tokens=effective_max_tokens,
                response_format={"type": "json_object"},
                reasoning={"effort": reasoning_effort, "exclude": not bool(stream_reasoning)},
                stream=bool(stream_reasoning),
                on_reasoning_delta=_on_reasoning_delta if stream_reasoning else None,
                raise_on_fail=True,
                retries=effective_retries,
                req_id_prefix=req_id_prefix,
                provider=binding.provider,
                base_url=binding.base_url,
                api_key=binding.api_key,
                timeout_s=effective_timeout_s,
            )
        except Exception as exc:
            if trace is not None:
                trace.record_failure(role=role_name, error=str(exc), fatal=bool(raise_on_fail))
            if raise_on_fail:
                raise
            # Optional enrichment and fail-closed review callers deliberately
            # request an empty result on provider failure. They may use a
            # deterministic baseline or reject the candidate, but never switch
            # to another provider/model.
            text = ""
        if trace is not None:
            # run_text returns only content, so retain a conservative zero-token
            # record while still exposing call count and latency.
            trace.record_call(
                role=role_name,
                model=binding.model,
                protocol="responses" if role_name == GENERATOR_ROLE else "chat_completions",
                usage={},
                elapsed_s=time.monotonic() - call_started_at,
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
    return strip_code_fences(text)


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
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return {}
