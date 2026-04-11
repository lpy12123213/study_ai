import unittest

from backend.agent.tools.utils import text_utils


class TextUtilsTests(unittest.TestCase):
    def test_strip_evidence_markers(self) -> None:
        self.assertEqual(text_utils._strip_evidence_markers("a [[1]] b"), "a b")
        self.assertEqual(text_utils._strip_evidence_markers("a ([[12]]) b"), "a b")

    def test_compact_snippet_collapses_whitespace(self) -> None:
        self.assertEqual(text_utils._compact_snippet("a \n  b\tc", max_chars=100), "a b c")

    def test_looks_like_pdf_url(self) -> None:
        self.assertTrue(text_utils._looks_like_pdf_url("https://example.test/a.pdf"))
        self.assertTrue(text_utils._looks_like_pdf_url("https://example.test/a.PDF?x=1"))
        self.assertFalse(text_utils._looks_like_pdf_url("https://example.test/a.html"))

    def test_postprocess_prefers_summary_as_snippet(self) -> None:
        out = text_utils._postprocess_web_search_result(
            {
                "title": "Test",
                "url": "https://example.test/x",
                "summary": "a [[1]]  b",
                "text": "ignored because summary exists",
            },
            max_snippet_chars=80,
        )
        self.assertEqual(out.get("snippet"), "a b")
        self.assertEqual(out.get("summary"), "a b")

    def test_postprocess_uses_highlights_when_no_summary(self) -> None:
        out = text_utils._postprocess_web_search_result(
            {
                "title": "Test",
                "url": "https://example.test/x",
                "highlights": ["Sign in to continue", "核心内容：定义与结论"],
                "text": "",
            },
            max_snippet_chars=80,
        )
        self.assertIn("核心内容", str(out.get("snippet") or ""))
        self.assertEqual(out.get("highlights"), ["核心内容：定义与结论"])


if __name__ == "__main__":
    unittest.main()
