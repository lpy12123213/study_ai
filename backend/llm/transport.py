from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import httpx

from backend.core.logging_utils import get_logger
from backend.core.settings import API_TIMEOUT

logger = get_logger(__name__)

_shared_http_client: Optional[httpx.AsyncClient] = None
_shared_http_client_factory: Any = None
_shared_http_client_loop: Optional[asyncio.AbstractEventLoop] = None
_shared_http_client_lock = asyncio.Lock()
_shared_http_limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)


def _timeout() -> httpx.Timeout:
    try:
        value = float(API_TIMEOUT or 120)
    except (TypeError, ValueError):
        value = 120.0
    return httpx.Timeout(max(1.0, min(value, 600.0)))


async def _close_http_client(client: Any) -> None:
    close = getattr(client, "aclose", None)
    if callable(close):
        try:
            await close()
        except Exception:
            logger.exception("llm_http_client_close_failed")


async def get_shared_llm_http_client(httpx_factory: Any = None) -> httpx.AsyncClient:
    global _shared_http_client, _shared_http_client_factory, _shared_http_client_loop
    factory = httpx_factory or httpx.AsyncClient
    loop = asyncio.get_running_loop()
    client = _shared_http_client
    if _matches_cache(client, factory, loop):
        return client
    async with _shared_http_client_lock:
        client = _shared_http_client
        if _matches_cache(client, factory, loop):
            return client
        if client is not None:
            await _close_http_client(client)
        try:
            client = factory(timeout=_timeout(), follow_redirects=True, http2=True, limits=_shared_http_limits)
        except ImportError:
            client = factory(timeout=_timeout(), follow_redirects=True, limits=_shared_http_limits)
        except TypeError:
            try:
                client = factory(timeout=_timeout(), follow_redirects=True)
            except TypeError:
                client = factory()
        _shared_http_client, _shared_http_client_factory, _shared_http_client_loop = client, factory, loop
        return client


def _matches_cache(client: Any, factory: Any, loop: asyncio.AbstractEventLoop) -> bool:
    return (
        client is not None
        and _shared_http_client_factory is factory
        and _shared_http_client_loop is loop
        and not bool(getattr(client, "is_closed", False))
    )


def _type_error_is_timeout_kwarg(exc: TypeError) -> bool:
    msg = str(exc)
    return "timeout" in msg and ("unexpected keyword" in msg or "unexpected" in msg or "got an unexpected" in msg)


async def close_shared_llm_http_client() -> None:
    global _shared_http_client, _shared_http_client_factory, _shared_http_client_loop
    client = _shared_http_client
    _shared_http_client = _shared_http_client_factory = _shared_http_client_loop = None
    if client is not None:
        await _close_http_client(client)


async def client_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: Dict[str, str],
    timeout_s: Optional[float],
) -> httpx.Response:
    try:
        return await client.get(url, headers=headers, timeout=timeout_s)
    except TypeError as exc:
        if not _type_error_is_timeout_kwarg(exc):
            raise
        return await client.get(url, headers=headers)


async def client_post(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout_s: Optional[float],
) -> httpx.Response:
    try:
        return await client.post(url, headers=headers, json=payload, timeout=timeout_s)
    except TypeError as exc:
        if not _type_error_is_timeout_kwarg(exc):
            raise
        return await client.post(url, headers=headers, json=payload)


def client_stream(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout_s: Optional[float],
):
    try:
        return client.stream(method, url, headers=headers, json=payload, timeout=timeout_s)
    except TypeError as exc:
        if not _type_error_is_timeout_kwarg(exc):
            raise
        return client.stream(method, url, headers=headers, json=payload)
