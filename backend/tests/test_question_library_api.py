import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

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

    def test_generate_stream_preserves_llm_request_failed_details(self) -> None:
        app = create_app()
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}

        llm_error = (
            "llm_request_failed status=404 model=Pro/moonshotai/Kimi-K2.5 "
            "provider=fireworks msg=Model not found"
        )

        with patch("backend.api.question_library.is_llm_configured", return_value=True), patch(
            "backend.api.question_library.build_source_pack",
            new=AsyncMock(
                return_value={
                    "subject": "高中数学",
                    "topic": "导数",
                    "study_markdown": "",
                    "facts": [],
                    "skills": [],
                    "common_mistakes": [],
                    "forbidden_patterns": [],
                }
            ),
        ), patch(
            "backend.api.question_library.generate_questions",
            new=AsyncMock(side_effect=RuntimeError(llm_error)),
        ), patch("backend.api.question_library.db_upsert_task", new=AsyncMock()), patch(
            "backend.api.question_library.db_append_task_event", new=AsyncMock()
        ), patch("backend.api.question_library.db_update_task_status", new=AsyncMock()):
            client = TestClient(app)
            with client.stream(
                "POST",
                "/api/question-library/generate",
                json={
                    "subject": "高中数学",
                    "topic": "导数",
                    "difficulty": "困难",
                    "question_type": "解答题",
                    "count": 1,
                    "use_study_archive": False,
                    "task_id": "ql-gen-test-err-1",
                },
            ) as resp:
                body = "\n".join(resp.iter_lines())

        app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 200)
        self.assertIn(llm_error, body)
        self.assertNotIn("no_questions_generated", body)
