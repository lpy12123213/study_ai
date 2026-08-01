from __future__ import annotations

import unittest
from unittest.mock import patch

from starlette.requests import Request

from backend.core import client_ip as client_ip_mod
from backend.core.client_ip import client_ip


class ClientIpTest(unittest.TestCase):
    """Shared trusted-proxy-aware client IP extraction (F8)."""

    def setUp(self) -> None:
        # The trusted-networks parse is lru_cached; reset between env patches.
        client_ip_mod._trusted_proxy_networks.cache_clear()

    def tearDown(self) -> None:
        client_ip_mod._trusted_proxy_networks.cache_clear()

    def _request(self, *, client_host: str = "203.0.113.9", headers: dict[str, str] | None = None) -> Request:
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/test",
            "raw_path": b"/api/test",
            "query_string": b"",
            "root_path": "",
            "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()],
            "client": (client_host, 54321),
            "server": ("testserver", 80),
        }
        return Request(scope)

    def test_default_no_trust_returns_client_host(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            request = self._request(headers={"X-Forwarded-For": "198.51.100.1"})
            self.assertEqual(client_ip(request), "203.0.113.9")

    def test_trusted_proxy_uses_forwarded_value(self) -> None:
        env = {"TRUST_PROXY_HEADERS": "1", "TRUSTED_PROXIES": "203.0.113.9"}
        with patch.dict("os.environ", env, clear=True):
            request = self._request(headers={"X-Forwarded-For": "198.51.100.1"})
            self.assertEqual(client_ip(request), "198.51.100.1")

    def test_untrusted_upstream_fails_closed_to_client_host(self) -> None:
        env = {"TRUST_PROXY_HEADERS": "1", "TRUSTED_PROXIES": "10.0.0.5"}
        with patch.dict("os.environ", env, clear=True):
            request = self._request(headers={"X-Forwarded-For": "198.51.100.1"})
            self.assertEqual(client_ip(request), "203.0.113.9")

    def test_header_rotation_cannot_change_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            r1 = self._request(headers={"X-Forwarded-For": "198.51.100.1"})
            r2 = self._request(headers={"X-Forwarded-For": "203.0.113.99"})
            self.assertEqual(client_ip(r1), "203.0.113.9")
            self.assertEqual(client_ip(r2), "203.0.113.9")
            self.assertEqual(client_ip(r1), client_ip(r2))

    def test_missing_client_host_returns_unknown(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            scope = {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/test",
                "raw_path": b"/api/test",
                "query_string": b"",
                "root_path": "",
                "headers": [],
                "server": ("testserver", 80),
            }
            self.assertEqual(client_ip(Request(scope)), "unknown")


if __name__ == "__main__":
    unittest.main()
