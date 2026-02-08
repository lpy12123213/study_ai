"""MCP client utilities for connecting to various AI services."""

from __future__ import annotations

import httpx
from typing import Optional, Dict, Any, AsyncIterator
import json

from backend.core.settings import (
    CHAT_API_KEY,
    CHAT_BASE_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    FIREWORKS_API_KEY,
    FIREWORKS_BASE_URL,
    ZHIPU_API_KEY,
    ZHIPU_BASE_URL,
)


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
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=payload,
            )
            response.raise_for_status()
            return response.json()
    
    async def chat_completion_stream(
        self,
        messages: list,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        tools: Optional[list] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream a chat completion request."""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        
        if tools:
            payload["tools"] = tools
        
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
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue


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
