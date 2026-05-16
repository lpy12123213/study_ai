from __future__ import annotations

import ipaddress
import unittest
from unittest.mock import AsyncMock, patch

import httpx

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
