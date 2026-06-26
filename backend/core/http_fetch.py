from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend
from httpx._config import create_ssl_context

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)

DEFAULT_FETCH_USER_AGENT = "StudyAI/1.0 (+https://local.study-ai.invalid)"
DEFAULT_ALLOWED_PORTS = {80, 443}

_shared_http_client: Optional[httpx.AsyncClient] = None
_shared_http_client_lock = asyncio.Lock()


class _PublicOnlyAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve and connect to the same public IP to reduce DNS rebinding risk."""

    def __init__(self) -> None:
        self._backend = AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        host_value = host.decode("ascii", errors="ignore") if isinstance(host, bytes) else str(host or "")
        ips = await resolve_host_ips(host_value)
        if not ips:
            raise ValueError("dns_resolution_failed")
        if any(not is_public_ip(ip) for ip in ips):
            raise ValueError("forbidden_ip")

        return await self._backend.connect_tcp(
            str(ips[0]),
            int(port),
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise ValueError("forbidden_unix_socket")


def _safe_fetch_transport() -> httpx.AsyncHTTPTransport:
    limits = httpx.Limits(max_connections=80, max_keepalive_connections=30)
    transport = httpx.AsyncHTTPTransport(trust_env=False, limits=limits)
    transport._pool = httpcore.AsyncConnectionPool(  # type: ignore[attr-defined]
        ssl_context=create_ssl_context(verify=True, cert=None, trust_env=False),
        max_connections=limits.max_connections,
        max_keepalive_connections=limits.max_keepalive_connections,
        keepalive_expiry=limits.keepalive_expiry,
        http1=True,
        http2=False,
        retries=0,
        network_backend=_PublicOnlyAsyncNetworkBackend(),
    )
    return transport


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
            transport=_safe_fetch_transport(),
            headers={"User-Agent": DEFAULT_FETCH_USER_AGENT},
            trust_env=False,
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
        current = await normalize_public_http_url(current, allowed_domains=allowed_domains)
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
