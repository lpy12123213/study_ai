from __future__ import annotations

import unittest

from backend.llm.reasoning_extract import coerce_reasoning_text, extract_reasoning_chunk


class TestLLMReasoningExtract(unittest.TestCase):
    def test_coerce_reasoning_text_handles_nested_parts(self) -> None:
        self.assertEqual(
            coerce_reasoning_text({"parts": ["a", {"content": "b"}, [{"summary": "c"}]]}),
            "abc",
        )

    def test_extract_reasoning_details_prefers_text_over_summary(self) -> None:
        chunk = extract_reasoning_chunk(
            choice0={},
            delta={"reasoning_details": [{"summary": "summary"}, {"text": "text-a"}, {"text": "text-b"}]},
            message={},
        )

        self.assertEqual(chunk, "text-atext-b")

    def test_extract_reasoning_details_uses_summary_when_no_text(self) -> None:
        chunk = extract_reasoning_chunk(
            choice0={},
            delta={"reasoning_details": [{"summary": "sum-a"}, {"summary": "sum-b"}]},
            message={},
        )

        self.assertEqual(chunk, "sum-asum-b")

    def test_extract_reasoning_chunk_uses_existing_fallback_order(self) -> None:
        chunk = extract_reasoning_chunk(
            choice0={"reasoning_content": "choice"},
            delta={},
            message={"reasoning": {"parts": [{"text": "message"}]}},
        )

        self.assertEqual(chunk, "message")


if __name__ == "__main__":
    unittest.main()
