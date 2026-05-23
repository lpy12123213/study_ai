from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional

from backend.workspace.chat.prompts import PLAN_TAG_CLOSE, PLAN_TAG_OPEN, get_system_prompt
from backend.workspace.chat.tools_spec import TOOLS
from backend.core.settings import (
    API_TIMEOUT,
    MAIN_MODEL,
    MAIN_MODEL_MAX_TOKENS,
    MAIN_MODEL_TEMPERATURE,
)
from backend.llm.client import _estimate_messages_tokens, cacheable_message, chat_completion, is_llm_configured

logger = logging.getLogger(__name__)


class ChatLLMMixin:
    def _context_message_max_chars(self) -> int:
        raw = (os.getenv("CHAT_CONTEXT_MESSAGE_MAX_CHARS") or "").strip()
        try:
            value = int(raw) if raw else 50_000
        except (TypeError, ValueError):
            value = 50_000
        return max(200, min(value, 200_000))

    def _context_total_max_chars(self) -> int:
        raw = (os.getenv("CHAT_CONTEXT_MAX_CHARS") or "").strip()
        try:
            value = int(raw) if raw else 200_000
        except (TypeError, ValueError):
            value = 200_000
        return max(2_000, min(value, 1_000_000))

    def _context_message_max_tokens(self) -> int:
        raw = (os.getenv("CHAT_CONTEXT_MESSAGE_MAX_TOKENS") or "").strip()
        if raw:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                value = 0
        else:
            value = int(math.ceil(self._context_message_max_chars() / 1.6))
        return max(128, min(value, 250_000))

    def _context_total_max_tokens(self) -> int:
        raw = (os.getenv("CHAT_CONTEXT_MAX_TOKENS") or "").strip()
        if raw:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                value = 0
        else:
            value = int(math.ceil(self._context_total_max_chars() / 1.6))
        return max(512, min(value, 1_000_000))

    def _clip_context_text(self, text: str, *, max_chars: int) -> str:
        value = str(text or "")
        if max_chars <= 0 or len(value) <= max_chars:
            return value
        if max_chars <= 1:
            return value[:max_chars]
        return value[: max_chars - 1].rstrip() + "…"

    def _clip_context_text_to_budget(self, text: str, *, max_chars: int, max_tokens: int, role: str) -> str:
        value = self._clip_context_text(text, max_chars=max_chars)
        if max_tokens <= 0 or not value:
            return ""

        def _tokens(candidate: str) -> int:
            return _estimate_messages_tokens([{"role": role, "content": candidate}])

        current_tokens = _tokens(value)
        while value and current_tokens > max_tokens:
            ratio = float(max_tokens) / float(current_tokens or 1)
            next_len = max(1, int(len(value) * ratio * 0.95))
            if next_len >= len(value):
                next_len = len(value) - 1
            if next_len <= 0:
                return ""
            value = self._clip_context_text(value, max_chars=next_len)
            current_tokens = _tokens(value)
        return value

    def _extract_plan_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        content = str(text or "")
        start = content.find(PLAN_TAG_OPEN)
        if start < 0:
            return None
        end = content.find(PLAN_TAG_CLOSE, start + len(PLAN_TAG_OPEN))
        if end < 0:
            return None
        payload = content[start + len(PLAN_TAG_OPEN) : end].strip()
        if not payload:
            return None
        # tolerate: <EXAM_PAPER_PLAN>```json {...}```</EXAM_PAPER_PLAN>
        payload = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", payload).strip()
        payload = re.sub(r"\s*```$", "", payload).strip()
        try:
            obj = json.loads(payload)
            return obj if isinstance(obj, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _extract_last_plan_from_history(self, history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for msg in reversed(history or []):
            if msg.get("role") != "assistant":
                continue
            plan = self._extract_plan_from_text(str(msg.get("content") or ""))
            if plan:
                return plan
        return None

    def _is_confirmation_message(self, user_message: str) -> bool:
        msg = (user_message or "").strip().lower()
        if not msg:
            return False
        keywords = {"确认", "开始", "开始组卷", "可以", "好的", "ok", "yes", "go"}
        return any(k in msg for k in keywords)

    def _build_messages(self, history: List[Dict[str, Any]], user_message: str, subject: str) -> List[Dict[str, Any]]:
        system_prompt = get_system_prompt(subject)
        system_msg: Dict[str, Any] = cacheable_message("system", system_prompt)
        messages: List[Dict[str, Any]] = [system_msg]
        per_message_max_chars = self._context_message_max_chars()
        per_message_max_tokens = self._context_message_max_tokens()
        total_budget_tokens = self._context_total_max_tokens()
        user_content = self._clip_context_text_to_budget(
            user_message,
            max_chars=per_message_max_chars,
            max_tokens=per_message_max_tokens,
            role="user",
        )
        user_msg: Dict[str, Any] = {"role": "user", "content": user_content}
        base_tokens = _estimate_messages_tokens([system_msg, user_msg])
        remaining_budget = max(0, total_budget_tokens - base_tokens)
        selected: List[Dict[str, Any]] = []
        trimmed_messages = 0

        for msg in reversed(history or []):
            role = str(msg.get("role") or "").strip()
            if role not in {"user", "assistant", "tool"}:
                continue

            content = self._clip_context_text_to_budget(
                str(msg.get("content") or ""),
                max_chars=per_message_max_chars,
                max_tokens=per_message_max_tokens,
                role=role,
            )
            if role != "assistant" and not content:
                continue

            if role == "assistant":
                msg_data: Dict[str, Any] = {"role": "assistant", "content": content}
                if msg.get("tool_calls"):
                    msg_data["tool_calls"] = msg.get("tool_calls")
            elif role == "tool":
                msg_data = {
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", "") or "",
                    "content": content,
                }
            else:
                msg_data = {"role": "user", "content": content}

            msg_tokens = _estimate_messages_tokens([msg_data])
            if msg_tokens > remaining_budget:
                trimmed_messages += 1
                continue

            selected.append(msg_data)
            remaining_budget -= msg_tokens

        if trimmed_messages > 0:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Earlier conversation messages were omitted only because the configured chat context "
                        f"budget was exceeded. Omitted messages: {trimmed_messages}."
                    ),
                }
            )
            logger.info(
                "Trimmed chat context",
                extra={
                    "trimmed_messages": trimmed_messages,
                    "history_messages": len(history or []),
                    "context_max_tokens": total_budget_tokens,
                    "context_message_max_tokens": per_message_max_tokens,
                    "context_max_chars": self._context_total_max_chars(),
                    "context_message_max_chars": per_message_max_chars,
                },
            )

        messages.extend(reversed(selected))
        messages.append(user_msg)
        return messages

    async def _call_api(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        include_tools: bool = True,
        tools_override: Optional[List[Dict[str, Any]]] = None,
        max_retries: int = 3,
        stream: bool = False,
        on_content_delta: Optional[Callable[[str], Awaitable[None]]] = None,
        on_reasoning_delta: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """Call the shared OpenAI-compatible LLM client.

        Returns a small, stable shape for the chat loop:
        `{ success, content, tool_calls, usage, finish_reason }`.
        """

        effective_model = (model or MAIN_MODEL).strip() or MAIN_MODEL

        if not is_llm_configured(scope="chat"):
            return {"success": False, "error": "llm_not_configured"}

        res = await chat_completion(
            messages=messages,
            model=effective_model,
            temperature=float(MAIN_MODEL_TEMPERATURE),
            max_tokens=int(MAIN_MODEL_MAX_TOKENS),
            tools=(tools_override if tools_override is not None else TOOLS) if include_tools else None,
            tool_choice="auto" if include_tools else None,
            stream=bool(stream),
            on_content_delta=on_content_delta,
            on_reasoning_delta=on_reasoning_delta,
            retries=max(1, int(max_retries or 1)),
            timeout_s=float(API_TIMEOUT or 30),
            req_id_prefix="chat",
            scope="chat",
        )

        # When tools are enabled, some providers return empty content. Tool calls are a success case.
        if not (str(res.content or "").strip() or (res.tool_calls and isinstance(res.tool_calls, list))):
            return {"success": False, "error": str(getattr(res, "error_code", "") or "llm_request_failed")}

        return {
            "success": True,
            "content": str(res.content or ""),
            "tool_calls": list(res.tool_calls or []),
            "usage": dict(res.usage or {}),
            "finish_reason": str(res.finish_reason or ""),
            "error_code": str(getattr(res, "error_code", "") or ""),
        }

    async def _call_api_streaming(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream the final assistant content (no tools) via the shared LLM client."""

        effective_model = (model or MAIN_MODEL).strip() or MAIN_MODEL
        if not is_llm_configured(scope="chat"):
            yield {"type": "error", "content": "llm_not_configured"}
            return

        queue: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
        done_sentinel: Optional[str] = None
        got_delta = False
        final_content = ""

        async def on_delta(text: str) -> None:
            nonlocal got_delta
            if not text:
                return
            got_delta = True
            await queue.put(str(text))

        async def _run() -> None:
            nonlocal final_content
            try:
                res = await chat_completion(
                    messages=messages,
                    model=effective_model,
                    temperature=float(MAIN_MODEL_TEMPERATURE),
                    max_tokens=int(MAIN_MODEL_MAX_TOKENS),
                    stream=True,
                    on_content_delta=on_delta,
                    raise_on_fail=False,
                    retries=3,
                    timeout_s=float(API_TIMEOUT or 60),
                    req_id_prefix="chat-final",
                    scope="chat",
                )
                final_content = str(res.content or "")
            finally:
                await queue.put(done_sentinel)

        bg = asyncio.create_task(_run())
        try:
            while True:
                item = await queue.get()
                if item is done_sentinel:
                    break
                yield {"type": "text_delta", "content": str(item or "")}
        finally:
            if not bg.done():
                bg.cancel()
                try:
                    await asyncio.wait_for(bg, timeout=2.0)
                except asyncio.CancelledError:
                    if not bg.cancelled():
                        raise
                except asyncio.TimeoutError:
                    logger.debug("chat_streaming_background_cancel_timeout")
                except Exception:
                    logger.warning("chat_streaming_background_cancel_failed", exc_info=True)

        # Some providers return the entire message in one shot even with stream=True.
        if not got_delta and final_content:
            yield {"type": "text_delta", "content": final_content}
        if not got_delta and not final_content:
            yield {"type": "error", "content": "llm_request_failed"}
