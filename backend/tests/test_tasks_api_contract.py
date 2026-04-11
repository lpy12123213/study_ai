from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.api.auth import require_auth


class TestTasksApiContract(unittest.TestCase):
    def _override_auth(self, app) -> None:
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}

    def test_router_is_mounted(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/tasks")
        # Auth will block; we only assert that the router is mounted.
        self.assertNotEqual(resp.status_code, 404)

    def test_submit_endpoints_return_task_id_shape(self) -> None:
        app = create_app()
        self._override_auth(app)
        client = TestClient(app)

        dummy_task = SimpleNamespace(task_id="task-1")

        with patch("backend.api.tasks.submit_deepthink_task", new=AsyncMock(return_value=dummy_task)):
            resp = client.post("/api/tasks/deepthink", json={"question": "1+1=?", "subject": "高中数学"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

        with patch("backend.api.tasks.submit_lesson_plan_task", new=AsyncMock(return_value=dummy_task)):
            resp = client.post("/api/tasks/lesson-plans/generate", json={"subject": "数学", "grade": "高一", "topic": "函数"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

        with patch("backend.api.tasks.submit_paper_compose_task", new=AsyncMock(return_value=dummy_task)):
            resp = client.post("/api/tasks/papers/compose", json={"paperName": "Demo"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

        with patch("backend.api.tasks.submit_generate_full_paper_task", new=AsyncMock(return_value=dummy_task)):
            resp = client.post("/api/tasks/papers/generate-full", json={"subject": "数学", "topic": "导数"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

        with patch("backend.api.tasks.submit_export_paper_task", new=AsyncMock(return_value=dummy_task)):
            resp = client.post("/api/tasks/export/papers/1", json={"format": "markdown"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

        with patch("backend.api.tasks.submit_export_study_archive_task", new=AsyncMock(return_value=dummy_task)):
            resp = client.post("/api/tasks/export/study-archives/1", json={"format": "markdown"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

        with (
            patch(
                "backend.study_materials.orchestrator_singleton.study_material_tasks.create_task",
                new=AsyncMock(return_value=dummy_task),
            ),
            patch(
                "backend.study_materials.orchestrator_singleton.study_material_tasks.continue_task",
                new=AsyncMock(return_value=dummy_task),
            ),
        ):
            resp = client.post("/api/tasks/study-materials/generate", json={"query": "导数", "subject": "高中数学"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

            resp = client.post("/api/tasks/study-materials/task-xyz/continue", json={"mode": "improve"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

        with (
            patch("backend.question_library.runner.create_crawl_task", new=AsyncMock(return_value=dummy_task)),
            patch("backend.question_library.runner.create_generate_task", new=AsyncMock(return_value=dummy_task)),
            patch("backend.question_library.runner.create_score_task", new=AsyncMock(return_value=dummy_task)),
        ):
            resp = client.post("/api/tasks/question-library/crawl", json={})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

            resp = client.post("/api/tasks/question-library/generate", json={})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

            resp = client.post("/api/tasks/question-library/score", json={})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

        app.dependency_overrides.clear()

    def test_stream_endpoint_is_mounted(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/tasks/task-1/stream")
        # Auth will block; we only assert that it is not a missing route.
        self.assertNotEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
