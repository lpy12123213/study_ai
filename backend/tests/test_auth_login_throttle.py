import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.testclient import TestClient

from backend.api import auth as auth_api
from backend.api.auth_schemas import LoginRequest


class AuthLoginThrottleTest(unittest.TestCase):
    def setUp(self):
        if hasattr(auth_api, "_login_attempt_limiter"):
            auth_api._login_attempt_limiter.reset()

    def tearDown(self):
        if hasattr(auth_api, "_login_attempt_limiter"):
            auth_api._login_attempt_limiter.reset()

    def test_repeated_failed_login_attempts_are_temporarily_locked(self):
        async def attempt():
            return await auth_api.login(
                LoginRequest(username="alice", password="wrong"),
                SimpleNamespace(client=SimpleNamespace(host="203.0.113.9")),
                Response(),
            )

        env = {
            "AUTH_LOGIN_MAX_FAILURES": "2",
            "AUTH_LOGIN_WINDOW_S": "60",
            "AUTH_LOGIN_LOCK_S": "30",
        }
        with (
            patch.dict("os.environ", env, clear=False),
            patch("backend.api.auth.authenticate_user", return_value=None),
            patch.object(auth_api.audit_logger, "log") as audit_log,
        ):
            for _ in range(2):
                with self.assertRaises(HTTPException) as cm:
                    asyncio.run(attempt())
                self.assertEqual(cm.exception.status_code, 401)

            with self.assertRaises(HTTPException) as cm:
                asyncio.run(attempt())

        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(cm.exception.detail, "login_locked")
        self.assertEqual(cm.exception.headers.get("Retry-After"), "30")
        actions = [call.kwargs.get("action") for call in audit_log.call_args_list]
        self.assertIn(auth_api.AuditAction.LOGIN_BRUTE_FORCE, actions)


class AuthCookieTest(unittest.TestCase):
    def test_auth_cookie_secure_defaults_off_for_local_env(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(auth_api._auth_cookie_secure())

    def test_auth_cookie_secure_defaults_on_for_production_env(self):
        with patch.dict("os.environ", {"ENV": "production"}, clear=True):
            self.assertTrue(auth_api._auth_cookie_secure())

    def test_login_sets_http_only_access_cookie(self):
        async def attempt():
            return await auth_api.login(
                LoginRequest(username="alice", password="secret"),
                SimpleNamespace(client=SimpleNamespace(host="203.0.113.9")),
                response,
            )

        response = Response()
        user = {
            "user_id": "u1",
            "username": "alice",
            "role": "admin",
            "created_at": None,
            "token_version": 1,
        }
        with (
            patch.dict("os.environ", {"AUTH_COOKIE_SECURE": "1"}, clear=False),
            patch("backend.api.auth.authenticate_user", return_value=user),
            patch("backend.api.auth.create_access_token", return_value="jwt-token"),
            patch.object(auth_api.audit_logger, "log"),
        ):
            out = asyncio.run(attempt())

        self.assertEqual(out.access_token, "jwt-token")
        header = response.headers.get("set-cookie") or ""
        self.assertIn(f"{auth_api.AUTH_ACCESS_COOKIE_NAME}=jwt-token", header)
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=lax", header)
        self.assertIn("Secure", header)

    def test_require_auth_accepts_access_cookie_without_bearer_header(self):
        app = FastAPI()

        @app.get("/whoami")
        async def whoami(user: dict = Depends(auth_api.require_auth)):
            return {"user_id": user.get("user_id"), "username": user.get("username")}

        with patch(
            "backend.api.auth.validate_access_token",
            return_value={"user_id": "u1", "username": "alice", "role": "admin", "jti": "j1", "exp": 9_999_999_999},
        ):
            client = TestClient(app, base_url="https://testserver")
            client.cookies.set(auth_api.AUTH_ACCESS_COOKIE_NAME, "cookie-token")
            resp = client.get("/whoami")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user_id"], "u1")

    def test_logout_clears_access_cookie(self):
        app = FastAPI()

        @app.post("/logout")
        async def logout(result: dict = Depends(auth_api.logout)):
            return result

        with patch(
            "backend.api.auth.validate_access_token",
            return_value={"user_id": "u1", "username": "alice", "role": "admin", "jti": "j1", "exp": 9_999_999_999},
        ):
            client = TestClient(app, base_url="https://testserver")
            client.cookies.set(auth_api.AUTH_ACCESS_COOKIE_NAME, "cookie-token", domain="testserver")
            resp = client.post("/logout")

        self.assertEqual(resp.status_code, 200)
        header = resp.headers.get("set-cookie") or ""
        self.assertIn(f"{auth_api.AUTH_ACCESS_COOKIE_NAME}=", header)
        self.assertIn("Max-Age=0", header)


if __name__ == "__main__":
    unittest.main()
