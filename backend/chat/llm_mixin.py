from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from backend.chat.prompts import PLAN_TAG_CLOSE, PLAN_TAG_OPEN, get_system_prompt
from backend.chat.tools_spec import TOOLS
from backend.config import (
    API_TIMEOUT,
    CHAT_PROVIDER,
    MAIN_MODEL,
    MAIN_MODEL_MAX_TOKENS,
    MAIN_MODEL_TEMPERATURE,
)
from backend.core import llm_console
from backend.core.settings import settings


class ChatLLMMixin:
    def _infer_provider_for_model(self, model: str) -> str:
        m = (model or "").strip()
        ml = m.lower()
        moonshot_like = (
            ml.startswith("moonshotai/")
            or ml.startswith("moonshot/")
            or ml.startswith("kimi-")
            or ml.startswith("moonshot-")
        )
        if moonshot_like and (settings.moonshot_api_key or "").strip():
            return "moonshot"
        if m.startswith("accounts/"):
            return "fireworks"
        if "/" in m:
            return "openrouter"
        return CHAT_PROVIDER

    def _resolve_chat_endpoint(self, model: str) -> Dict[str, str]:
        provider = self._infer_provider_for_model(model)
        if provider == "fireworks":
            return {
                "provider": "fireworks",
                "base_url": (settings.fireworks_base_url or "").rstrip("/"),
                "api_key": (settings.fireworks_api_key or "").strip(),
            }
        if provider == "moonshot":
            return {
                "provider": "moonshot",
                "base_url": (settings.moonshot_base_url or "").rstrip("/"),
                "api_key": (settings.moonshot_api_key or "").strip(),
            }
        return {
            "provider": "openrouter",
            "base_url": (settings.openrouter_base_url or "").rstrip("/"),
            "api_key": (settings.openrouter_api_key or "").strip(),
        }

    def _chat_headers(self, provider: str, api_key: str) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider == "openrouter":
            if (settings.review_http_referer or "").strip():
                headers["HTTP-Referer"] = settings.review_http_referer
            if (settings.review_x_title or "").strip():
                headers["X-Title"] = settings.review_x_title
        return headers

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
        except Exception:
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
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        for msg in history or []:
            role = msg.get("role")
            if role == "user":
                messages.append({"role": "user", "content": msg.get("content") or ""})
            elif role == "assistant":
                msg_data: Dict[str, Any] = {"role": "assistant", "content": msg.get("content") or ""}
                if msg.get("tool_calls"):
                    msg_data["tool_calls"] = msg.get("tool_calls")
                messages.append(msg_data)
            elif role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.get("tool_call_id", "") or "",
                        "content": msg.get("content") or "",
                    }
                )

        messages.append({"role": "user", "content": user_message})
        return messages

    async def _call_api(
        self,
        client: httpx.AsyncClient,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        include_tools: bool = True,
        tools_override: Optional[List[Dict[str, Any]]] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        effective_model = (model or MAIN_MODEL).strip() or MAIN_MODEL
        endpoint = self._resolve_chat_endpoint(effective_model)
        base_url = endpoint["base_url"]
        provider = endpoint["provider"]
        api_key = endpoint["api_key"]
        if not api_key:
            return {"success": False, "error": f"未配置 {provider} API Key（当前模型: {effective_model}）"}

        normalized_model = effective_model
        if provider == "moonshot" and "/" in normalized_model:
            normalized_model = normalized_model.split("/")[-1]

        effective_temperature = float(MAIN_MODEL_TEMPERATURE)
        if provider == "moonshot" and normalized_model.lower().startswith("kimi-"):
            effective_temperature = 1.0

        req_id_base = f"chat-api-{uuid.uuid4().hex[:8]}"

        def _elapsed_s(start_ts: float) -> float:
            try:
                return max(0.0, time.time() - float(start_ts))
            except Exception:
                return 0.0

        for attempt in range(max(1, int(max_retries or 1))):
            req_id = f"{req_id_base}-{attempt + 1}"
            start_ts = llm_console.log_start(
                req_id=req_id,
                provider=provider,
                model=normalized_model,
                stream=False,
                temperature=effective_temperature,
                max_tokens=int(MAIN_MODEL_MAX_TOKENS),
                base_url=base_url,
            )
            try:
                payload: Dict[str, Any] = {
                    "model": normalized_model,
                    "messages": messages,
                    "max_tokens": int(MAIN_MODEL_MAX_TOKENS),
                    "temperature": effective_temperature,
                }
                if include_tools:
                    payload["tools"] = tools_override if tools_override is not None else TOOLS
                    payload["tool_choice"] = "auto"

                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=self._chat_headers(provider, api_key),
                    json=payload,
                    timeout=float(API_TIMEOUT or 30),
                )

                if response.status_code == 200:
                    data = response.json()
                    llm_console.log_end(
                        req_id=req_id,
                        elapsed_s=_elapsed_s(start_ts),
                        finish_reason=str(
                            (data.get("choices", [{}])[0] or {}).get("finish_reason") if isinstance(data, dict) else ""
                        ),
                        usage=dict(data.get("usage") or {}) if isinstance(data, dict) else {},
                        content_chars=len(
                            str((((data.get("choices", [{}])[0] or {}).get("message") or {}).get("content") or ""))
                            if isinstance(data, dict)
                            else ""
                        ),
                    )
                    return {"success": True, "data": data} if isinstance(data, dict) else {"success": False, "error": "invalid_response"}

                last_error = RuntimeError(f"{provider} API error: {response.status_code} - {response.text}")
            except Exception as exc:
                last_error = exc
            finally:
                if last_error is not None:
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), finish_reason="error")

            await asyncio.sleep(0.6 * (attempt + 1))

        return {"success": False, "error": str(last_error) if last_error else "api_error"}

    async def _call_api_streaming(
        self,
        client: httpx.AsyncClient,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        include_tools: bool = True,
        tools_override: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        effective_model = (model or MAIN_MODEL).strip() or MAIN_MODEL
        endpoint = self._resolve_chat_endpoint(effective_model)
        base_url = endpoint["base_url"]
        provider = endpoint["provider"]
        api_key = endpoint["api_key"]
        if not api_key:
            yield {"type": "error", "content": f"未配置 {provider} API Key（当前模型: {effective_model}）"}
            return

        normalized_model = effective_model
        if provider == "moonshot" and "/" in normalized_model:
            normalized_model = normalized_model.split("/")[-1]

        effective_temperature = float(MAIN_MODEL_TEMPERATURE)
        if provider == "moonshot" and normalized_model.lower().startswith("kimi-"):
            effective_temperature = 1.0

        payload: Dict[str, Any] = {
            "model": normalized_model,
            "messages": messages,
            "max_tokens": int(MAIN_MODEL_MAX_TOKENS),
            "temperature": effective_temperature,
            "stream": True,
        }
        # Final answer streaming: do NOT include tools to reduce token & latency.

        req_id = f"chat-stream-{uuid.uuid4().hex[:8]}"
        start_ts = llm_console.log_start(
            req_id=req_id,
            provider=provider,
            model=normalized_model,
            stream=True,
            temperature=effective_temperature,
            max_tokens=int(MAIN_MODEL_MAX_TOKENS),
            base_url=base_url,
        )

        try:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers=self._chat_headers(provider, api_key),
                json=payload,
                timeout=float(API_TIMEOUT or 60),
            ) as response:
                if response.status_code != 200:
                    text = await response.aread()
                    yield {"type": "error", "error": f"{provider} API error: {response.status_code} - {text!s}"}
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except Exception:
                        continue

                    if not isinstance(chunk, dict):
                        continue
                    choices = chunk.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    delta = choices[0].get("delta") if isinstance(choices[0], dict) else {}
                    if not isinstance(delta, dict):
                        continue

                    if "content" in delta and delta["content"]:
                        text = str(delta.get("content") or "")
                        llm_console.log_delta(req_id=req_id, channel="content", text=text)
                        yield {"type": "text_delta", "content": text}
        except Exception as exc:
            yield {"type": "error", "content": str(exc)}
        finally:
            llm_console.log_end(req_id=req_id, elapsed_s=max(0.0, time.time() - float(start_ts or time.time())))
