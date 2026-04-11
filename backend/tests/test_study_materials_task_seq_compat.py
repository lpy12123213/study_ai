import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.api.auth import require_auth
from backend.app import create_app


class TestStudyMaterialsTaskSeqCompat(unittest.TestCase):
    def _override_auth(self, app) -> None:
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}

    def test_get_task_uses_first_seq_when_present(self) -> None:
        app = create_app()
        self._override_auth(app)

        dummy = SimpleNamespace(
            task_id="sm-1",
            query="q",
            user_id="u-1",
            status="done",
            error=None,
            created_at_s=1.0,
            updated_at_s=2.0,
            first_seq=5,
            last_seq=9,
            last_success_step=None,
            last_failed_step=None,
            last_success_stage="",
            last_failed_stage="",
            per_kp_state={},
            search_summary_by_kp={},
        )

        with patch("backend.api.study_materials._tasks.get_task", new=AsyncMock(return_value=dummy)):
            client = TestClient(app)
            resp = client.get("/api/study-materials/tasks/sm-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["task_id"], "sm-1")
        self.assertEqual(data["first_seq"], 5)
        self.assertEqual(data["last_seq"], 9)

    def test_get_task_falls_back_to_seq_offset(self) -> None:
        app = create_app()
        self._override_auth(app)

        dummy = SimpleNamespace(
            task_id="sm-2",
            query="q",
            user_id="u-1",
            status="done",
            error=None,
            created_at_s=1.0,
            updated_at_s=2.0,
            # No `first_seq` field (older runtime task shape).
            seq_offset=7,
            last_seq=9,
            last_success_step=None,
            last_failed_step=None,
            last_success_stage="",
            last_failed_stage="",
            per_kp_state={},
            search_summary_by_kp={},
        )

        with patch("backend.api.study_materials._tasks.get_task", new=AsyncMock(return_value=dummy)):
            client = TestClient(app)
            resp = client.get("/api/study-materials/tasks/sm-2")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["task_id"], "sm-2")
        self.assertEqual(data["first_seq"], 8)
        self.assertEqual(data["last_seq"], 9)

