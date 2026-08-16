from __future__ import annotations

import unittest

from backend.core.config_check import check_config, log_config_check


class TestConfigCheck(unittest.TestCase):
    @staticmethod
    def _model_config(*, api_key: str = "configured") -> dict:
        return {
            "active_provider": "openrouter",
            "routes": {"chat": "openrouter", "lesson_plan": "openrouter"},
            "providers": {
                "openrouter": {
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key": api_key,
                }
            },
        }

    def test_provider_key_is_required_for_active_chat_provider(self) -> None:
        result = check_config(
            {
                "JWT_SECRET": "real-secret",
                "ADMIN_PASSWORD": "real-password",
            },
            model_config=self._model_config(api_key=""),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["missing"][0]["key"], "providers.openrouter.api_key")

    def test_recommended_flags_do_not_fail_config(self) -> None:
        result = check_config(
            {
                "JWT_SECRET": "dev-jwt-secret-change-me",
                "ADMIN_PASSWORD": "dev-admin-change-me",
            },
            model_config=self._model_config(),
        )

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["counts"]["recommended"], 2)

    def test_multiple_workers_flag_process_local_rate_limiter(self) -> None:
        result = check_config(
            {
                "JWT_SECRET": "real-secret",
                "ADMIN_PASSWORD": "real-password",
                "WEB_CONCURRENCY": "2",
            },
            model_config=self._model_config(),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["optional"][0]["key"], "WEB_CONCURRENCY")

    def test_log_config_check_does_not_use_reserved_log_record_keys(self) -> None:
        result = log_config_check(
            {
                "JWT_SECRET": "dev-jwt-secret-change-me",
                "ADMIN_PASSWORD": "dev-admin-change-me",
            },
            model_config=self._model_config(),
        )

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["counts"]["recommended"], 2)
