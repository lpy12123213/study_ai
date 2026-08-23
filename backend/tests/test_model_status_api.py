"""Tests for /api/system/model-status and the shared model-health state."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.api.auth import require_auth
from backend.app import create_app
from backend.core.model_health import get_model_health, record_model_health, reset_model_health_for_tests


class ModelHealthStateTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_model_health_for_tests()

    def test_record_aggregates_role_status(self) -> None:
        payload = record_model_health(
            [
                {"config": "models.study_materials_thinking", "model": "m1", "status": "ok", "error_code": "", "hint": ""},
                {"config": "models.study_materials_writer", "model": "m2", "status": "failed", "error_code": "4xx", "hint": "x"},
            ]
        )
        self.assertEqual(payload["status"], "failed")
        self.assertIsNotNone(payload["checked_at"])
        self.assertEqual([r["status"] for r in payload["roles"]], ["ok", "failed"])

    def test_degraded_and_skipped_states(self) -> None:
        self.assertEqual(record_model_health([])["status"], "skipped")
        self.assertEqual(
            record_model_health(
                [{"config": "c", "model": "m", "status": "degraded", "error_code": "timeout", "hint": ""}]
            )["status"],
            "degraded",
        )

    def test_get_returns_copy_not_internal_state(self) -> None:
        record_model_health([{"config": "c", "model": "m", "status": "ok", "error_code": "", "hint": ""}])
        snapshot = get_model_health()
        snapshot["roles"][0]["model"] = "mutated"
        self.assertEqual(get_model_health()["roles"][0]["model"], "m")


class ModelStatusEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_model_health_for_tests()
        self.app = create_app()
        self.app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        reset_model_health_for_tests()

    def test_model_status_returns_recorded_state(self) -> None:
        record_model_health(
            [{"config": "models.study_materials_writer", "model": "m", "status": "ok", "error_code": "", "hint": ""}]
        )

        resp = self.client.get("/api/model-status")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["roles"][0]["config"], "models.study_materials_writer")

    def test_model_status_refresh_reruns_self_check(self) -> None:
        from backend.core import settings as settings_mod
        from backend.llm.result import ChatCompletionResult

        mock_chat = AsyncMock(return_value=ChatCompletionResult(error_code="4xx"))
        with patch("backend.llm.client.chat_completion", new=mock_chat), patch.object(
            settings_mod, "STUDY_MATERIALS_THINKING_MODEL", "bad-model"
        ), patch.object(settings_mod, "STUDY_MATERIALS_WRITER_MODEL", "bad-model"):
            resp = self.client.get("/api/model-status?refresh=1")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # 两个 role 指向同一模型：只 ping 一次，但状态应为 failed。
        self.assertEqual(mock_chat.await_count, 1)
        self.assertEqual(body["status"], "failed")
        self.assertTrue(body["roles"])
        self.assertIn("config/model.json", body["roles"][0]["hint"])


if __name__ == "__main__":
    unittest.main()
