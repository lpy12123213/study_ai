from __future__ import annotations

import ipaddress
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend.core import http_fetch
from backend.core.http_fetch import normalize_public_http_url, safe_fetch_get


class HttpFetchSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_normalize_public_http_url_rejects_private_ip(self) -> None:
        with self.assertRaises(ValueError):
            await normalize_public_http_url("http://127.0.0.1/internal")

    async def test_normalize_public_http_url_resolves_public_hosts(self) -> None:
        with patch(
            "backend.core.http_fetch.resolve_host_ips",
            new=AsyncMock(return_value=[ipaddress.ip_address("93.184.216.34")]),
        ):
            self.assertEqual(
                await normalize_public_http_url("https://example.com/path"),
                "https://example.com/path",
            )

    async def test_safe_fetch_get_revalidates_redirect_targets(self) -> None:
        class FakeClient:
            async def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
                return httpx.Response(302, headers={"location": "http://127.0.0.1/latest"})

        with patch(
            "backend.core.http_fetch.resolve_host_ips",
            new=AsyncMock(return_value=[ipaddress.ip_address("93.184.216.34")]),
        ):
            with self.assertRaises(ValueError):
                await safe_fetch_get("https://example.com/start", client=FakeClient())  # type: ignore[arg-type]

    async def test_safe_fetch_get_rechecks_dns_immediately_before_request(self) -> None:
        calls: list[str] = []

        class FakeClient:
            async def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
                calls.append("get")
                return httpx.Response(200, text="ok")

        with patch(
            "backend.core.http_fetch.resolve_host_ips",
            new=AsyncMock(
                side_effect=[
                    [ipaddress.ip_address("93.184.216.34")],
                    [ipaddress.ip_address("127.0.0.1")],
                ]
            ),
        ):
            with self.assertRaises(ValueError):
                await safe_fetch_get("https://example.com/start", client=FakeClient(), max_redirects=0)  # type: ignore[arg-type]

        self.assertEqual(calls, [])

    async def test_public_only_network_backend_connects_to_checked_public_ip(self) -> None:
        calls: list[tuple[str, int]] = []
        sentinel = object()

        class FakeBackend:
            async def connect_tcp(self, host, port, **kwargs):  # noqa: ANN001, ANN003
                calls.append((host, port))
                return sentinel

        backend = http_fetch._PublicOnlyAsyncNetworkBackend()  # type: ignore[attr-defined]
        backend._backend = FakeBackend()  # type: ignore[attr-defined]

        with patch(
            "backend.core.http_fetch.resolve_host_ips",
            new=AsyncMock(return_value=[ipaddress.ip_address("93.184.216.34")]),
        ):
            stream = await backend.connect_tcp("example.com", 443)

        self.assertIs(stream, sentinel)
        self.assertEqual(calls, [("93.184.216.34", 443)])

    async def test_public_only_network_backend_rejects_private_resolution_before_connect(self) -> None:
        calls: list[tuple[str, int]] = []

        class FakeBackend:
            async def connect_tcp(self, host, port, **kwargs):  # noqa: ANN001, ANN003
                calls.append((host, port))
                return object()

        backend = http_fetch._PublicOnlyAsyncNetworkBackend()  # type: ignore[attr-defined]
        backend._backend = FakeBackend()  # type: ignore[attr-defined]

        with patch(
            "backend.core.http_fetch.resolve_host_ips",
            new=AsyncMock(return_value=[ipaddress.ip_address("127.0.0.1")]),
        ):
            with self.assertRaises(ValueError):
                await backend.connect_tcp("example.com", 443)

        self.assertEqual(calls, [])
