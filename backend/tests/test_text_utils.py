import unittest

from backend.agent.tools import text_utils


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


if __name__ == "__main__":
    unittest.main()

