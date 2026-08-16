import unittest
from unittest.mock import patch

from backend.llm.client import cap_max_tokens, cap_max_tokens_for_messages


class TestLlmTokenCaps(unittest.TestCase):
    def test_cap_max_tokens_uses_context_length_and_completion_limit(self) -> None:
        messages = [{"role": "user", "content": "hello"}]
        values = {"reserve_tokens": 128, "input_multiplier": 1}
        with patch("backend.llm.model_limits.model_context_value", side_effect=lambda key, default=None: values.get(key, default)):
            capped = cap_max_tokens(
                messages=messages,
                context_length=512,
                requested_max_tokens=500,
                max_completion_tokens=64,
            )
        self.assertEqual(capped, 64)

    def test_cap_max_tokens_for_messages_uses_model_context_lookup(self) -> None:
        messages = [{"role": "user", "content": "hello"}]
        values = {"lengths": {"unit-test-model": 192}, "reserve_tokens": 128, "input_multiplier": 1}
        with patch("backend.llm.model_limits.model_context_value", side_effect=lambda key, default=None: values.get(key, default)):
            capped = cap_max_tokens_for_messages(
                messages=messages,
                model="unit-test-model",
                requested_max_tokens=100,
            )
        self.assertLess(capped, 100)
        self.assertGreaterEqual(capped, 1)


if __name__ == "__main__":
    unittest.main()
