"""Shared trusted-proxy-aware client IP extraction.

All callers (request-id middleware, API/auth rate limiters, share password
limiter, audit logs) use this single helper so proxy-header trust semantics
are consistent across the app.  By default only ``request.client.host`` is
trusted (fail-closed); forwarding headers are parsed only when
``TRUST_PROXY_HEADERS=1`` AND the direct peer belongs to ``TRUSTED_PROXIES``.
"""

from __future__ import annotations

import ipaddress
import os
import re
from functools import lru_cache

from fastapi import Request

from backend.core.logging_utils import get_logger
from backend.core.settings import env_bool

logger = get_logger(__name__)

_MAX_CLIENT_IP_LENGTH = 80


def _parse_trusted_proxies(raw: str) -> list[ipaddress._BaseNetwork]:
    value = str(raw or "").strip()
    if not value:
        return []
    parts = re.split(r"[,\n;\s]+", value)
    nets: list[ipaddress._BaseNetwork] = []
    for p in parts:
        p = str(p or "").strip()
        if not p:
            continue
        if p == "*":
            # Wildcard trust makes proxy headers trivially spoofable; ignore and warn.
            continue
        try:
            if "/" in p:
                nets.append(ipaddress.ip_network(p, strict=False))
                continue
            addr = ipaddress.ip_address(p)
            if addr.version == 4:
                nets.append(ipaddress.ip_network(f"{p}/32"))
            else:
                nets.append(ipaddress.ip_network(f"{p}/128"))
        except ValueError:
            continue
        except Exception:
            logger.exception("failed to parse TRUSTED_PROXIES entry", extra={"value": p})
    return nets


@lru_cache(maxsize=1)
def _trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    raw = str(os.getenv("TRUSTED_PROXIES") or "").strip()
    return tuple(_parse_trusted_proxies(raw))


def _is_trusted_proxy(request: Request) -> bool:
    nets = _trusted_proxy_networks()
    if not nets:
        return False
    host = (request.client.host if request.client else "") or ""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    except Exception:
        logger.exception("failed to parse request.client.host", extra={"host": host})
        return False
    return any(ip in net for net in nets)


def client_ip(request: Request) -> str:
    """Best-effort client IP extraction with optional proxy header trust.

    Returns a value capped at 80 chars. When proxy headers are not trusted
    (default) or the direct peer is not a configured trusted proxy, returns
    ``request.client.host`` (fail-closed).
    """

    if env_bool("TRUST_PROXY_HEADERS", default=False) and _is_trusted_proxy(request):
        # RFC 7239 Forwarded: for=...
        forwarded = str(request.headers.get("Forwarded") or "").strip()
        if forwarded:
            try:
                first = forwarded.split(",", 1)[0]
                m = re.search(r'(?i)(?:^|;|\s)for=("[^"]+"|[^;\s]+)', first)
                if m:
                    v = str(m.group(1) or "").strip().strip('"')
                    if v.startswith("[") and "]" in v:
                        v = v[1 : v.index("]")]
                    # Strip IPv4 :port (keep IPv6 intact).
                    if ":" in v and "." in v:
                        host, _, port = v.partition(":")
                        if port.isdigit():
                            v = host
                    if v and v.lower() != "unknown":
                        return v[:_MAX_CLIENT_IP_LENGTH]
            except (IndexError, ValueError):
                logger.debug("failed to parse Forwarded header", exc_info=True)

        # X-Forwarded-For can be a list: client, proxy1, proxy2...
        xff = str(request.headers.get("X-Forwarded-For") or "").strip()
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first[:_MAX_CLIENT_IP_LENGTH]
        xri = str(request.headers.get("X-Real-IP") or "").strip()
        if xri:
            return xri[:_MAX_CLIENT_IP_LENGTH]
        cfip = str(request.headers.get("CF-Connecting-IP") or "").strip()
        if cfip:
            return cfip[:_MAX_CLIENT_IP_LENGTH]

    host = (request.client.host if request.client else "") or "unknown"
    return host[:_MAX_CLIENT_IP_LENGTH]


def warn_proxy_settings_on_startup() -> None:
    """Emit security warnings for risky proxy-header settings."""

    raw = str(os.getenv("TRUSTED_PROXIES") or "").strip()
    if raw:
        parts = [p for p in re.split(r"[,\n;\s]+", raw) if p]
        if "*" in parts:
            logger.warning(
                "trusted_proxies_wildcard_forbidden",
                extra={"trusted_proxies": raw},
            )

    if env_bool("TRUST_PROXY_HEADERS", default=False) and not _trusted_proxy_networks():
        # This is a common misconfig: enabling proxy headers without defining trusted proxy IPs
        # effectively disables all proxy-header parsing (fail-closed), which surprises users.
        logger.warning("trust_proxy_headers_enabled_but_no_trusted_proxies")
