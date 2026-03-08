from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import create_app


class TestSecurityHeadersAndErrorEnvelope(unittest.TestCase):
    def test_security_headers_exist_for_api_and_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dist = Path(tmpdir) / "dist"
            assets = dist / "assets"
            assets.mkdir(parents=True, exist_ok=True)
            (dist / "index.html").write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")
            (assets / "app.123.js").write_text("console.log('ok')", encoding="utf-8")

            with patch.object(app_module, "DIST_PATH", dist):
                with patch("backend.app.init_db", new=AsyncMock()):
                    with patch("backend.app.close_crawler", new=AsyncMock()):
                        with patch("backend.app.close_proxy_http_client", new=AsyncMock()):
                            app = create_app()
                            with TestClient(app) as client:
                                api_res = client.get("/api/health")
                                self.assertEqual(api_res.status_code, 200)
                                for key in (
                                    "X-Content-Type-Options",
                                    "X-Frame-Options",
                                    "Referrer-Policy",
                                    "Permissions-Policy",
                                    "Cross-Origin-Opener-Policy",
                                    "X-Request-ID",
                                ):
                                    self.assertIn(key, api_res.headers)

                                asset_res = client.get("/assets/app.123.js")
                                self.assertEqual(asset_res.status_code, 200)
                                self.assertIn("immutable", str(asset_res.headers.get("Cache-Control") or ""))
                                for key in (
                                    "X-Content-Type-Options",
                                    "X-Frame-Options",
                                    "Referrer-Policy",
                                    "Permissions-Policy",
                                    "Cross-Origin-Opener-Policy",
                                    "X-Request-ID",
                                ):
                                    self.assertIn(key, asset_res.headers)

    def test_error_envelope_includes_code_and_request_id(self) -> None:
        with patch("backend.app.init_db", new=AsyncMock()):
                    with patch("backend.app.close_crawler", new=AsyncMock()):
                        with patch("backend.app.close_proxy_http_client", new=AsyncMock()):
                            app = create_app()
                    with TestClient(app, raise_server_exceptions=False) as client:
                        not_found = client.get("/api/this-route-does-not-exist")
                        self.assertEqual(not_found.status_code, 404)
                        payload = not_found.json()
                        self.assertIn("error", payload)
                        self.assertIn("code", payload["error"])
                        self.assertIn("request_id", payload["error"])
                        self.assertEqual(payload["error"]["request_id"], not_found.headers.get("X-Request-ID"))

                        validation = client.post("/api/auth/login", json={})
                        self.assertEqual(validation.status_code, 422)
                        payload = validation.json()
                        self.assertIn("error", payload)
                        self.assertIn("code", payload["error"])
                        self.assertIn("request_id", payload["error"])
                        self.assertEqual(payload["error"]["request_id"], validation.headers.get("X-Request-ID"))

                        with patch("backend.api.auth.authenticate_user", side_effect=RuntimeError("boom")):
                            internal = client.post("/api/auth/login", json={"username": "any", "password": "any"})
                        self.assertEqual(internal.status_code, 500)
                        payload = internal.json()
                        self.assertEqual(payload.get("detail"), "internal_error")
                        self.assertEqual(payload.get("error", {}).get("code"), "internal_error")
                        self.assertEqual(payload.get("error", {}).get("request_id"), internal.headers.get("X-Request-ID"))
