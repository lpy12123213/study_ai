from __future__ import annotations

import unittest

from backend.core.config_check import check_config, log_config_check


class TestConfigCheck(unittest.TestCase):
    def test_provider_key_is_required_for_active_chat_provider(self) -> None:
        result = check_config(
            {
                "CHAT_PROVIDER": "openrouter",
                "LESSON_PLAN_PROVIDER": "moonshot",
                "OPENROUTER_API_KEY": "",
                "MOONSHOT_API_KEY": "ms-key",
                "JWT_SECRET": "real-secret",
                "ADMIN_PASSWORD": "real-password",
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["missing"][0]["key"], "OPENROUTER_API_KEY")

    def test_recommended_flags_do_not_fail_config(self) -> None:
        result = check_config(
            {
                "CHAT_PROVIDER": "fireworks",
                "LESSON_PLAN_PROVIDER": "fireworks",
                "FIREWORKS_API_KEY": "fw-key",
                "JWT_SECRET": "dev-jwt-secret-change-me",
                "ADMIN_PASSWORD": "dev-admin-change-me",
            }
        )

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["counts"]["recommended"], 2)

    def test_multiple_workers_flag_process_local_rate_limiter(self) -> None:
        result = check_config(
            {
                "CHAT_PROVIDER": "fireworks",
                "LESSON_PLAN_PROVIDER": "fireworks",
                "FIREWORKS_API_KEY": "fw-key",
                "JWT_SECRET": "real-secret",
                "ADMIN_PASSWORD": "real-password",
                "WEB_CONCURRENCY": "2",
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["optional"][0]["key"], "WEB_CONCURRENCY")

    def test_log_config_check_does_not_use_reserved_log_record_keys(self) -> None:
        result = log_config_check(
            {
                "CHAT_PROVIDER": "fireworks",
                "LESSON_PLAN_PROVIDER": "fireworks",
                "FIREWORKS_API_KEY": "fw-key",
                "JWT_SECRET": "dev-jwt-secret-change-me",
                "ADMIN_PASSWORD": "dev-admin-change-me",
            }
        )

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["counts"]["recommended"], 2)
