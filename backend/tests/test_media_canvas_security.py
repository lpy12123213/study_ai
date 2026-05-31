import ipaddress
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.api import media
from backend.api import papers
from backend.api.auth import require_auth
from backend.api import canvas
from backend.api.canvas import _sanitize_question_html
from backend.app import create_app
from backend.core.audit import AuditAction
from backend.core.subjects import get_all_subjects
from backend.media import generated as generated_media


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


class TestControlledQuestionAccess(unittest.IsolatedAsyncioTestCase):
    async def test_canvas_render_question_rate_limited_by_user(self) -> None:
        with patch.object(canvas._QUESTION_RENDER_LIMITER, "allow", new=AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException) as ctx:
                await canvas.render_question("123", user={"user_id": "u-1"})

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail, "rate_limited")

    async def test_canvas_render_question_audits_successful_access(self) -> None:
        fake_crawler = AsyncMock()
        fake_crawler.base_url = "https://zujuan.xkw.com"
        fake_crawler.get_question_detail.return_value = {
            "success": True,
            "question_id": "123",
            "stem_html": "<p>题干</p>",
        }

        with patch.object(canvas._QUESTION_RENDER_LIMITER, "allow", new=AsyncMock(return_value=True)), patch.object(
            canvas,
            "resolve_subject",
            return_value="高中数学",
        ), patch.object(canvas, "get_crawler", new=AsyncMock(return_value=fake_crawler)), patch.object(
            canvas.audit_logger,
            "log",
        ) as audit_log:
            result = await canvas.render_question("123", subject="高中数学", edu_level="", user={"user_id": "u-1"})

        self.assertTrue(result["success"])
        audit_log.assert_called_once()
        kwargs = audit_log.call_args.kwargs
        self.assertEqual(kwargs["user_id"], "u-1")
        self.assertEqual(kwargs["action"], AuditAction.QUESTION_RENDER)
        self.assertEqual(kwargs["details"]["question_id"], "123")

    async def test_paper_download_link_rate_limited_by_user(self) -> None:
        with patch.object(papers._PAPER_DOWNLOAD_LINK_LIMITER, "allow", new=AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException) as ctx:
                await papers.get_download_link(1, user={"user_id": "u-1"})

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail, "rate_limited")

    async def test_paper_download_link_audits_successful_access(self) -> None:
        paper = {
            "paper_name": "测试卷",
            "questions": [{"question_id": "123", "source_url": "https://zujuan.xkw.com/q/123"}],
        }
        with patch.object(papers._PAPER_DOWNLOAD_LINK_LIMITER, "allow", new=AsyncMock(return_value=True)), patch.object(
            papers,
            "get_paper",
            new=AsyncMock(return_value=paper),
        ), patch.object(papers, "get_question_cache", new=AsyncMock(return_value={})), patch.object(
            papers.audit_logger,
            "log",
        ) as audit_log:
            result = await papers.get_download_link(7, user={"user_id": "u-1"})

        self.assertTrue(result["success"])
        self.assertEqual(result["question_ids"], ["123"])
        audit_log.assert_called_once()
        kwargs = audit_log.call_args.kwargs
        self.assertEqual(kwargs["user_id"], "u-1")
        self.assertEqual(kwargs["action"], AuditAction.PAPER_DOWNLOAD_LINK)
        self.assertEqual(kwargs["details"]["paper_id"], 7)
        self.assertEqual(kwargs["details"]["question_ids"], ["123"])


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


class TestGeneratedMediaPublishing(unittest.IsolatedAsyncioTestCase):
    async def test_publish_generated_bytes_scopes_filenames_by_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(generated_media, "_GENERATED_DIR", Path(tmpdir)):
                with patch.object(generated_media, "upsert_generated_file", new=AsyncMock()):
                    alice = await generated_media.publish_generated_bytes(
                        b"same image bytes",
                        user_id="alice",
                        ext=".svg",
                        file_type="image",
                        mime_type="image/svg+xml",
                    )
                    bob = await generated_media.publish_generated_bytes(
                        b"same image bytes",
                        user_id="bob",
                        ext=".svg",
                        file_type="image",
                        mime_type="image/svg+xml",
                    )

        self.assertEqual(alice["sha256"], bob["sha256"])
        self.assertNotEqual(alice["filename"], bob["filename"])
        self.assertTrue(str(alice["filename"]).endswith(".svg"))
        self.assertTrue(str(bob["filename"]).endswith(".svg"))
