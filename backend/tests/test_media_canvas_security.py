import ipaddress
import os
import unittest
from unittest.mock import patch

from backend.api import media
from backend.api.canvas import _sanitize_question_html
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
