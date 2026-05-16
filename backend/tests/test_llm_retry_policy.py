import unittest
from pathlib import Path
from unittest.mock import patch

import httpx


class LlmRetryPolicyTest(unittest.TestCase):
    def test_retry_policy_uses_retry_after_header_when_present(self):
        from backend.llm.retry_policy import RetryPolicy

        resp = httpx.Response(429, headers={"Retry-After": "3.5"})
        self.assertEqual(RetryPolicy(jitter_s=0.0).http_retry_delay(resp, attempt=0), 3.5)

    def test_retry_policy_has_minimum_backoff_for_retryable_errors(self):
        from backend.llm.retry_policy import RetryPolicy

        policy = RetryPolicy(base_delay_s=0.1, min_delay_s=0.5, jitter_s=0.0)
        self.assertEqual(policy.retryable_status_delay(attempt=0), 0.5)
        self.assertGreater(policy.retryable_status_delay(attempt=3), 0.5)

    def test_response_handlers_do_not_embed_hardcoded_backoff(self):
        root = Path(__file__).resolve().parents[2]
        src = (root / "backend" / "llm" / "response_handlers.py").read_text(encoding="utf-8")
        self.assertNotIn("asyncio.sleep(0.2)", src)
        self.assertNotIn("random.random()", src)
        self.assertNotIn("2 ** kwargs", src)

    def test_llm_concurrency_limit_uses_shared_configured_semaphore(self):
        from backend.llm import concurrency

        concurrency._semaphore = None
        concurrency._semaphore_limit = None
        with patch.dict("os.environ", {"MAX_CONCURRENT_LLM_REQUESTS": "2"}):
            sem = concurrency.get_llm_concurrency_semaphore()
            self.assertIs(sem, concurrency.get_llm_concurrency_semaphore())
            self.assertEqual(concurrency._semaphore_limit, 2)


if __name__ == "__main__":
    unittest.main()
