"""MCP client utilities for connecting to various AI services."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Dict, Optional

import httpx

from backend.llm import console as llm_console
from backend.core.logging_utils import get_logger
from backend.core.settings import (
    CHAT_API_KEY,
    CHAT_BASE_URL,
    FIREWORKS_API_KEY,
    FIREWORKS_BASE_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    ZHIPU_API_KEY,
    ZHIPU_BASE_URL,
)

logger = get_logger(__name__)


class OpenAICompatibleClient:
    """Client for OpenAI-compatible APIs."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: float = 120.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat_completion(
        self,
        messages: list,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Send a chat completion request."""
        req_id = f"mcp-client-{uuid.uuid4().hex[:8]}"
        start_ts = llm_console.log_start(
            req_id=req_id,
            provider="openai_compat",
            model=str(model or ""),
            stream=bool(stream),
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            base_url=str(self.base_url or ""),
        )
        finish_reason = ""
        usage: Dict[str, Any] = {}
        content_chars = 0
        err = ""

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            payload["tools"] = tools

        if stream:
            payload["stream"] = True

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                try:
                    choice0 = data.get("choices", [{}])[0] if isinstance(data, dict) else {}
                    finish_reason = str(choice0.get("finish_reason") or "")
                    msg = choice0.get("message", {}) if isinstance(choice0.get("message"), dict) else {}
                    content_text = str(msg.get("content") or "")
                    if content_text:
                        content_chars = len(content_text)
                        llm_console.log_delta(req_id=req_id, channel="content", text=content_text)
                except Exception:
                    finish_reason = ""
                if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                    usage = dict(data.get("usage") or {})
                return data
        except Exception as exc:
            err = str(exc)
            raise
        finally:
            elapsed_s = 0.0
            try:
                elapsed_s = max(0.0, time.time() - float(start_ts)) if start_ts else 0.0
            except Exception:
                elapsed_s = 0.0
            llm_console.log_end(
                req_id=req_id,
                elapsed_s=elapsed_s,
                finish_reason=finish_reason,
                usage=usage,
                content_chars=content_chars,
                error=err,
            )

    async def chat_completion_stream(
        self,
        messages: list,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        tools: Optional[list] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream a chat completion request."""
        req_id = f"mcp-stream-{uuid.uuid4().hex[:8]}"
        start_ts = llm_console.log_start(
            req_id=req_id,
            provider="openai_compat",
            model=str(model or ""),
            stream=True,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            base_url=str(self.base_url or ""),
        )
        finish_reason = ""
        usage: Dict[str, Any] = {}
        content_chars = 0
        err = ""

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        try:
                            choice0 = (chunk.get("choices") or [{}])[0] if isinstance(chunk, dict) else {}
                            delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}
                            content = delta.get("content")
                            if isinstance(content, str) and content:
                                content_chars += len(content)
                                llm_console.log_delta(req_id=req_id, channel="content", text=content)
                            fr = choice0.get("finish_reason")
                            if isinstance(fr, str) and fr:
                                finish_reason = fr
                            if isinstance(chunk, dict) and isinstance(chunk.get("usage"), dict):
                                usage = dict(chunk.get("usage") or {})
                        except Exception:
                            logger.debug("mcp_llm_stream_parse_failed", extra={"req_id": req_id}, exc_info=True)

                        yield chunk
        except Exception as exc:
            err = str(exc)
            raise
        finally:
            elapsed_s = 0.0
            try:
                elapsed_s = max(0.0, time.time() - float(start_ts)) if start_ts else 0.0
            except Exception:
                elapsed_s = 0.0
            llm_console.log_end(
                req_id=req_id,
                elapsed_s=elapsed_s,
                finish_reason=finish_reason,
                usage=usage,
                content_chars=content_chars,
                error=err,
            )


def get_openrouter_client() -> OpenAICompatibleClient:
    """Get an OpenRouter client."""
    return OpenAICompatibleClient(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
    )


def get_fireworks_client() -> OpenAICompatibleClient:
    """Get a Fireworks client."""
    return OpenAICompatibleClient(
        api_key=FIREWORKS_API_KEY,
        base_url=FIREWORKS_BASE_URL,
    )


def get_zhipu_client() -> OpenAICompatibleClient:
    """Get a Zhipu (BigModel) client."""
    return OpenAICompatibleClient(
        api_key=ZHIPU_API_KEY,
        base_url=ZHIPU_BASE_URL,
    )


def get_default_client() -> OpenAICompatibleClient:
    """Get the default chat client based on configuration."""
    return OpenAICompatibleClient(
        api_key=CHAT_API_KEY,
        base_url=CHAT_BASE_URL,
    )
