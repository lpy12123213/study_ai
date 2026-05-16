from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import httpx

from backend.core.helpers import get_logger

logger = get_logger(__name__)

DEFAULT_FETCH_USER_AGENT = "StudyAI/1.0 (+https://local.study-ai.invalid)"
DEFAULT_ALLOWED_PORTS = {80, 443}

_shared_http_client: Optional[httpx.AsyncClient] = None
_shared_http_client_lock = asyncio.Lock()


def _normalize_domain_items(items: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    for item in items or []:
        value = str(item or "").strip().lower()
        if value:
            out.append(value)
    return out


def _is_domain_allowed(host: str, allowed_domains: Iterable[str] | None) -> bool:
    allowed = _normalize_domain_items(allowed_domains)
    if not allowed:
        return True
    host = str(host or "").strip().lower()
    for domain in allowed:
        if domain == "*":
            return True
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    return bool(getattr(ip, "is_global", False))


async def resolve_host_ips(host: str) -> list[ipaddress._BaseAddress]:
    value = str(host or "").strip()
    if not value:
        return []

    try:
        return [ipaddress.ip_address(value)]
    except ValueError:
        pass

    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(value, None, type=socket.SOCK_STREAM)
    except (OSError, RuntimeError):
        return []

    out: list[ipaddress._BaseAddress] = []
    seen: set[str] = set()
    for _family, _type, _proto, _canonname, sockaddr in infos:
        try:
            raw = str(sockaddr[0])
        except (IndexError, TypeError):
            continue
        if not raw or raw in seen:
            continue
        seen.add(raw)
        try:
            out.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    return out


async def normalize_public_http_url(
    url: str,
    *,
    allowed_domains: Iterable[str] | None = None,
    allowed_ports: set[int] | None = None,
) -> str:
    value = str(url or "").strip()
    if not value:
        raise ValueError("empty_url")
    if value.startswith("//"):
        value = f"https:{value}"

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("invalid_scheme")
    if not parsed.netloc:
        raise ValueError("missing_host")
    if parsed.username or parsed.password:
        raise ValueError("forbidden_userinfo")

    port = parsed.port
    allowed = allowed_ports or DEFAULT_ALLOWED_PORTS
    if port is not None and int(port) not in allowed:
        raise ValueError("forbidden_port")

    host = str(parsed.hostname or "").strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("forbidden_host")
    if not _is_domain_allowed(host, allowed_domains):
        raise ValueError("host_not_allowed")

    ips = await resolve_host_ips(host)
    if not ips:
        raise ValueError("dns_resolution_failed")
    if any(not is_public_ip(ip) for ip in ips):
        raise ValueError("forbidden_ip")

    return value


async def get_shared_fetch_http_client() -> httpx.AsyncClient:
    global _shared_http_client
    if _shared_http_client is not None:
        return _shared_http_client

    async with _shared_http_client_lock:
        if _shared_http_client is not None:
            return _shared_http_client
        _shared_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
            headers={"User-Agent": DEFAULT_FETCH_USER_AGENT},
            limits=httpx.Limits(max_connections=80, max_keepalive_connections=30),
        )
        return _shared_http_client


async def close_shared_fetch_http_client() -> None:
    global _shared_http_client
    async with _shared_http_client_lock:
        client = _shared_http_client
        _shared_http_client = None
    if client is None:
        return
    try:
        await client.aclose()
    except (RuntimeError, httpx.HTTPError):
        logger.warning("shared_fetch_http_client_close_failed", exc_info=True)


async def safe_fetch_get(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    headers: dict[str, str] | None = None,
    timeout_s: float = 30.0,
    allowed_domains: Iterable[str] | None = None,
    max_redirects: int = 5,
) -> httpx.Response:
    current = await normalize_public_http_url(url, allowed_domains=allowed_domains)
    http_client = client or await get_shared_fetch_http_client()
    redirects = max(0, min(int(max_redirects or 0), 10))

    for _ in range(redirects + 1):
        response = await http_client.get(
            current,
            headers=headers,
            timeout=max(1.0, min(float(timeout_s or 30.0), 120.0)),
            follow_redirects=False,
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = str(response.headers.get("location") or "").strip()
        if not location:
            return response
        current = await normalize_public_http_url(urljoin(current, location), allowed_domains=allowed_domains)

    raise ValueError("too_many_redirects")
