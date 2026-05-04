import ipaddress
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import backend.app as app_module
from backend.api import media
from backend.api.auth import require_auth
from backend.api.canvas import _sanitize_question_html
from backend.app import create_app
from backend.core.subjects import get_all_subjects


class TestCanvasSanitization(unittest.TestCase):
    def test_sanitize_removes_unsafe_anchor_href(self) -> None:
        html = '<a href="javascript:alert(1)" onclick="evil()">bad</a>'

        sanitized = _sanitize_question_html(html, base_url="https://zujuan.xkw.com")

        self.assertIn(">bad</a>", sanitized)
        self.assertNotIn("javascript:", sanitized)
        self.assertNotIn("onclick", sanitized)
        self.assertNotIn("href=", sanitized)

    def test_sanitize_rewrites_safe_images_to_proxy(self) -> None:
        html = '<img src="/static/question.png" onload="evil()">'

        sanitized = _sanitize_question_html(html, base_url="https://zujuan.xkw.com")

        self.assertIn("/api/media/proxy?url=https%3A%2F%2Fzujuan.xkw.com%2Fstatic%2Fquestion.png", sanitized)
        self.assertNotIn("onload", sanitized)


class TestMediaProxyNormalization(unittest.IsolatedAsyncioTestCase):
    async def test_normalize_remote_url_accepts_allowed_public_image_host(self) -> None:
        async def fake_resolve(_host: str):
            return [ipaddress.ip_address("93.184.216.34")]

        with patch.dict(os.environ, {"MEDIA_PROXY_ALLOWED_DOMAINS": "example.com"}):
            with patch("backend.api.media._resolve_host_ips", new=fake_resolve):
                normalized = await media._normalize_remote_url("https://example.com/assets/test.png")

        self.assertEqual(normalized, "https://example.com/assets/test.png")

    async def test_normalize_remote_url_rejects_non_allowed_host(self) -> None:
        async def fake_resolve(_host: str):
            return [ipaddress.ip_address("93.184.216.34")]

        with patch.dict(os.environ, {"MEDIA_PROXY_ALLOWED_DOMAINS": "example.com"}):
            with patch("backend.api.media._resolve_host_ips", new=fake_resolve):
                with self.assertRaisesRegex(ValueError, "host_not_allowed"):
                    await media._normalize_remote_url("https://not-example.com/assets/test.png")

    async def test_normalize_remote_url_rejects_non_http_scheme(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_scheme"):
            await media._normalize_remote_url("ftp://example.com/test.png")

    async def test_normalize_remote_url_rejects_private_ip_targets(self) -> None:
        async def fake_resolve(_host: str):
            return [ipaddress.ip_address("10.0.0.8")]

        with patch.dict(os.environ, {"MEDIA_PROXY_ALLOWED_DOMAINS": "example.com"}):
            with patch("backend.api.media._resolve_host_ips", new=fake_resolve):
                with self.assertRaisesRegex(ValueError, "forbidden_ip"):
                    await media._normalize_remote_url("https://example.com/assets/test.png")


class TestSubjects(unittest.TestCase):
    def test_get_all_subjects_deduplicates_names(self) -> None:
        names = [item["name"] for item in get_all_subjects()]
        self.assertEqual(len(names), len(set(names)))


class TestGeneratedDocumentFilenameWhitelist(unittest.TestCase):
    def test_generated_document_extensions_are_allowed_for_download_and_zip(self) -> None:
        sha = "a" * 64
        docx_name = f"{sha}.docx"
        zip_name = f"{sha}.zip"

        self.assertTrue(media._is_safe_generated_filename(docx_name))
        self.assertTrue(media._is_safe_generated_filename(zip_name))

        from backend.api.exports import _is_safe_generated_filename as exports_filename_ok

        self.assertTrue(exports_filename_ok(docx_name))
        self.assertTrue(exports_filename_ok(zip_name))


class TestGeneratedMediaDownloadApi(unittest.TestCase):
    def test_generated_docx_and_zip_are_served_as_download_attachments(self) -> None:
        app = create_app()
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                generated_dir = Path(tmpdir)

                for ext, payload in ((".docx", b"fake docx bytes"), (".zip", b"PK\x03\x04fake zip bytes")):
                    filename = f"{'a' * 64}{ext}"
                    (generated_dir / filename).write_bytes(payload)
                    meta = {
                        "filename": filename,
                        "user_id": "u-1",
                        "file_type": ext.lstrip("."),
                        "mime_type": "application/octet-stream",
                        "bytes": len(payload),
                        "created_at": "",
                        "expires_at": "",
                    }

                    with patch.object(app_module, "init_db", new=AsyncMock()):
                        with patch.object(app_module, "close_crawler", new=AsyncMock()):
                            with patch.object(app_module, "close_proxy_http_client", new=AsyncMock()):
                                with patch("backend.api.media.GENERATED_DIR", generated_dir):
                                    with patch("backend.api.media.get_generated_file", new=AsyncMock(return_value=meta)):
                                        with TestClient(app) as client:
                                            res = client.get(f"/api/media/generated/{filename}")

                    self.assertEqual(res.status_code, 200)
                    self.assertEqual(res.content, payload)
                    content_disposition = str(res.headers.get("content-disposition") or "")
                    self.assertIn("attachment;", content_disposition)
                    self.assertIn(filename, content_disposition)
        finally:
            app.dependency_overrides.clear()
