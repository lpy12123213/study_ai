from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.api import ws
from backend.api.auth import AUTH_ACCESS_COOKIE_NAME


class WsTokenPriorityTest(unittest.TestCase):
    """WebSocket auth credential priority: HttpOnly cookie beats legacy ?token= (F4)."""

    def _socket(self, *, cookie: str = "") -> SimpleNamespace:
        cookies = {}
        if cookie:
            cookies[AUTH_ACCESS_COOKIE_NAME] = cookie
        return SimpleNamespace(cookies=cookies)

    def test_cookie_only_is_used(self) -> None:
        self.assertEqual(ws._resolve_ws_token(self._socket(cookie="cookie-token"), ""), "cookie-token")

    def test_query_only_is_legacy_fallback(self) -> None:
        self.assertEqual(ws._resolve_ws_token(self._socket(), "query-token"), "query-token")

    def test_cookie_wins_when_both_present(self) -> None:
        self.assertEqual(ws._resolve_ws_token(self._socket(cookie="cookie-token"), "query-token"), "cookie-token")

    def test_neither_returns_empty(self) -> None:
        self.assertEqual(ws._resolve_ws_token(self._socket(), ""), "")


if __name__ == "__main__":
    unittest.main()
