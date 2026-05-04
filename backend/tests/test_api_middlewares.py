import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.middleware.rate_limit import SlidingWindowRateLimiter, register_rate_limit_middleware
from backend.api.middleware.request_id import ensure_request_id, register_request_id_middleware
from backend.api.middleware.security_headers import register_security_headers_middleware
from backend.core.logging_utils import set_request_id


class TestApiMiddlewares(unittest.IsolatedAsyncioTestCase):
    async def test_sliding_window_rate_limiter_blocks_after_limit(self) -> None:
        limiter = SlidingWindowRateLimiter(max_requests=2, window_s=60, max_keys=10)

        self.assertTrue(await limiter.allow("client-a"))
        self.assertTrue(await limiter.allow("client-a"))
        self.assertFalse(await limiter.allow("client-a"))
        self.assertTrue(await limiter.allow("client-b"))


class TestApiMiddlewareRegistration(unittest.TestCase):
    def tearDown(self) -> None:
        set_request_id("")

    def test_ensure_request_id_uses_incoming_header(self) -> None:
        set_request_id("")
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"x-request-id", b"rid-1")]})

        self.assertEqual(ensure_request_id(request), "rid-1")

    def test_security_headers_are_added(self) -> None:
        app = FastAPI()
        register_security_headers_middleware(app)

        @app.get("/ping")
        def ping() -> dict[str, str]:
            return {"ok": "1"}

        res = TestClient(app).get("/ping")

        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")

    def test_rate_limit_middleware_returns_error_envelope(self) -> None:
        app = FastAPI()

        @app.get("/api/ping")
        def ping() -> dict[str, str]:
            return {"ok": "1"}

        env = {
            "API_RATE_LIMIT_MAX_REQUESTS": "1",
            "API_RATE_LIMIT_WINDOW_S": "60",
            "API_RATE_LIMIT_MAX_KEYS": "100",
        }
        with patch.dict(os.environ, env, clear=False):
            register_request_id_middleware(app, client_ip=lambda request: "127.0.0.1")
            register_rate_limit_middleware(app, client_ip=lambda request: "127.0.0.1")

        client = TestClient(app)

        self.assertEqual(client.get("/api/ping").status_code, 200)
        limited = client.get("/api/ping")

        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json().get("error", {}).get("code"), "rate_limited")
        self.assertTrue(limited.headers.get("X-Request-ID"))


if __name__ == "__main__":
    unittest.main()
