from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from backend.llm import tokenizer


class TokenizerFallbackTests(unittest.TestCase):
    def tearDown(self) -> None:
        tokenizer._tiktoken_encoder = None
        tokenizer._tiktoken_unavailable = False
        tokenizer._tiktoken_import_failed_logged = False
        tokenizer._tiktoken_encode_failed_logged = False

    def test_runtime_tiktoken_initialization_error_falls_back_once(self) -> None:
        calls = 0

        def fail_get_encoding(_name: str) -> object:
            nonlocal calls
            calls += 1
            raise RuntimeError("network unavailable")

        fake_tiktoken = types.SimpleNamespace(get_encoding=fail_get_encoding)

        tokenizer._tiktoken_encoder = None
        tokenizer._tiktoken_unavailable = False
        with patch.dict("os.environ", {"STUDY_AI_ENABLE_TIKTOKEN": "1"}), patch.dict(
            "sys.modules", {"tiktoken": fake_tiktoken}
        ):
            self.assertGreater(tokenizer.estimate_text_tokens("数学高考模拟"), 0)
            self.assertEqual(tokenizer.tokenizer_backend(), "heuristic")
            self.assertGreater(tokenizer.estimate_text_tokens("再次估算"), 0)

        self.assertEqual(calls, 1)

    def test_tiktoken_is_opt_in_to_avoid_runtime_downloads(self) -> None:
        calls = 0

        def fail_get_encoding(_name: str) -> object:
            nonlocal calls
            calls += 1
            raise AssertionError("tiktoken should not be initialized by default")

        fake_tiktoken = types.SimpleNamespace(get_encoding=fail_get_encoding)

        with patch.dict("os.environ", {"STUDY_AI_ENABLE_TIKTOKEN": ""}), patch.dict(
            "sys.modules", {"tiktoken": fake_tiktoken}
        ):
            self.assertGreater(tokenizer.estimate_text_tokens("数学高考模拟"), 0)
            self.assertEqual(tokenizer.tokenizer_backend(), "heuristic")

        self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()
