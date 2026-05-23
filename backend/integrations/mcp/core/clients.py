"""MCP client utilities for connecting to OpenAI-compatible services.

This module intentionally delegates HTTP + provider resolution to `backend.llm.client`
so the codebase has a single implementation of:
- base_url / api_key selection
- OpenRouter headers (HTTP-Referer / X-Title)
- retry / circuit-breaker behavior
- record/replay fixtures
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, Optional

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
from backend.llm.client import chat_completion


def _guess_provider(base_url: str) -> str:
    url = str(base_url or "").strip().lower()
    if "openrouter" in url:
        return "openrouter"
    if "fireworks" in url:
        return "fireworks"
    if "bigmodel" in url or "zhipu" in url:
        return "zhipu"
    return "openai_compat"


class OpenAICompatibleClient:
    """Very small wrapper around `backend.llm.client.chat_completion`.

    Kept mainly for backwards compatibility with older MCP code paths. Prefer
    calling `backend.llm.client.chat_completion` directly for new code.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: float = 120.0,
    ):
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.timeout = float(timeout or 120.0)

    def _provider(self) -> str:
        return _guess_provider(self.base_url)

    async def chat_completion(
        self,
        messages: list,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Return an OpenAI-like response dict (best-effort)."""

        res = await chat_completion(
            messages=list(messages or []),
            model=str(model or "").strip(),
            temperature=float(temperature),
            max_tokens=int(max_tokens or 0),
            tools=list(tools or []) if tools else None,
            stream=bool(stream),
            raise_on_fail=False,
            retries=3,
            timeout_s=float(self.timeout),
            req_id_prefix="mcp-client",
            provider=self._provider(),
            base_url=self.base_url,
            api_key=self.api_key,
        )

        message: Dict[str, Any] = {"content": str(res.content or "")}
        if res.tool_calls:
            message["tool_calls"] = list(res.tool_calls)

        return {
            "choices": [
                {
                    "message": message,
                    "finish_reason": str(res.finish_reason or ""),
                }
            ],
            "usage": dict(res.usage or {}),
        }

    async def chat_completion_stream(
        self,
        messages: list,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        tools: Optional[list] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream an OpenAI-like delta payload (best-effort).

        This adapts `backend.llm.client.chat_completion(stream=True)` callbacks into a
        generator that yields `{"choices":[{"delta":{"content":"..."}}]}` chunks.
        """

        q: asyncio.Queue[Dict[str, Any] | None] = asyncio.Queue()

        async def on_content_delta(text: str) -> None:
            if not text:
                return
            await q.put({"choices": [{"delta": {"content": text}}]})

        async def runner() -> None:
            try:
                res = await chat_completion(
                    messages=list(messages or []),
                    model=str(model or "").strip(),
                    temperature=float(temperature),
                    max_tokens=int(max_tokens or 0),
                    tools=list(tools or []) if tools else None,
                    stream=True,
                    on_content_delta=on_content_delta,
                    raise_on_fail=False,
                    retries=3,
                    timeout_s=float(self.timeout),
                    req_id_prefix="mcp-stream",
                    provider=self._provider(),
                    base_url=self.base_url,
                    api_key=self.api_key,
                )
                await q.put({"choices": [{"delta": {}, "finish_reason": str(res.finish_reason or "")}], "usage": dict(res.usage or {})})
            finally:
                await q.put(None)

        asyncio.create_task(runner())

        while True:
            item = await q.get()
            if item is None:
                break
            yield item


def get_openrouter_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)


def get_fireworks_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(api_key=FIREWORKS_API_KEY, base_url=FIREWORKS_BASE_URL)


def get_zhipu_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(api_key=ZHIPU_API_KEY, base_url=ZHIPU_BASE_URL)


def get_default_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(api_key=CHAT_API_KEY, base_url=CHAT_BASE_URL)

