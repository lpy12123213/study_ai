import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.api.auth import require_auth
from backend.question_library import preview_store


class TestQuestionLibraryApi(unittest.TestCase):
    def test_router_is_mounted(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/question-library/items")
        # Auth will block; we only assert that it's not a 404.
        self.assertNotEqual(resp.status_code, 404)

    def test_bulk_delete_endpoint_exists(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.post("/api/question-library/items/bulk-delete", json={"question_ids": ["q1"]})
        # Auth will block; we only assert that it's not a 404/405.
        self.assertNotIn(resp.status_code, {404, 405})

    def test_latest_pending_preview_returns_current_users_latest_draft(self) -> None:
        app = create_app()
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}

        with tempfile.TemporaryDirectory() as tmpdir:
            original_dir = preview_store._PREVIEWS_DIR
            preview_store._PREVIEWS_DIR = Path(tmpdir)
            try:
                preview_store.save_preview(
                    {
                        "preview_id": "pv-old",
                        "status": "pending_review",
                        "user_id": "u-1",
                        "subject": "高中数学",
                        "topic": "导数",
                        "draft_questions": [{"question_id": "q-old", "stem": "s", "answer": "a", "analysis": "x"}],
                        "created_at_s": 100,
                    }
                )
                preview_store.save_preview(
                    {
                        "preview_id": "pv-new",
                        "status": "pending_review",
                        "user_id": "u-1",
                        "subject": "高中数学",
                        "topic": "圆锥曲线",
                        "draft_questions": [{"question_id": "q-new", "stem": "s", "answer": "a", "analysis": "x"}],
                        "created_at_s": 200,
                    }
                )
                preview_store.save_preview(
                    {
                        "preview_id": "pv-other-user",
                        "status": "pending_review",
                        "user_id": "u-2",
                        "subject": "高中数学",
                        "topic": "概率",
                        "draft_questions": [{"question_id": "q-other", "stem": "s", "answer": "a", "analysis": "x"}],
                        "created_at_s": 300,
                    }
                )
                preview_store.save_preview(
                    {
                        "preview_id": "pv-committed",
                        "status": "committed",
                        "user_id": "u-1",
                        "subject": "高中数学",
                        "topic": "数列",
                        "draft_questions": [{"question_id": "q-committed", "stem": "s", "answer": "a", "analysis": "x"}],
                        "created_at_s": 400,
                    }
                )

                client = TestClient(app)
                resp = client.get("/api/question-library/previews/latest/pending")
            finally:
                preview_store._PREVIEWS_DIR = original_dir
                app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["preview"]["preview_id"], "pv-new")
        self.assertEqual(data["preview"]["topic"], "圆锥曲线")
