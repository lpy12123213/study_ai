import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.api.auth import require_auth
from backend.question_library import preview_store


class TestQuestionLibraryApi(unittest.TestCase):
    def _override_auth(self, app) -> None:
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}

    def _with_temp_preview_dirs(self):
        tmpdir = tempfile.TemporaryDirectory()
        original_previews = preview_store._PREVIEWS_DIR
        original_sessions = getattr(preview_store, "_SESSIONS_DIR", None)
        preview_store._PREVIEWS_DIR = Path(tmpdir.name) / "previews"
        if original_sessions is not None:
            preview_store._SESSIONS_DIR = Path(tmpdir.name) / "sessions"
        return tmpdir, original_previews, original_sessions

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
        self._override_auth(app)

        tmp, original_dir, original_sessions = self._with_temp_preview_dirs()
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
            if original_sessions is not None:
                preview_store._SESSIONS_DIR = original_sessions
            app.dependency_overrides.clear()
            tmp.cleanup()

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["preview"]["preview_id"], "pv-new")
        self.assertEqual(data["preview"]["topic"], "圆锥曲线")

    def test_generate_creates_persisted_session_and_discard_archives_it(self) -> None:
        app = create_app()
        self._override_auth(app)
        llm_source_pack = {
            "subject": "高中数学",
            "topic": "导数",
            "study_markdown": "",
            "facts": [],
            "skills": [],
            "common_mistakes": [],
            "forbidden_patterns": [],
        }
        drafts = [{"stem": "题干 A", "answer": "答案 A", "analysis": "解析 A"}]

        tmp, original_previews, original_sessions = self._with_temp_preview_dirs()
        try:
            with patch("backend.api.question_library.is_llm_configured", return_value=True), patch(
                "backend.api.question_library.build_source_pack", new=AsyncMock(return_value=llm_source_pack)
            ), patch(
                "backend.api.question_library.generate_questions", new=AsyncMock(return_value=drafts)
            ), patch("backend.api.question_library.db_upsert_task", new=AsyncMock()), patch(
                "backend.api.question_library.db_append_task_event", new=AsyncMock()
            ), patch("backend.api.question_library.db_update_task_status", new=AsyncMock()), patch(
                "backend.api.question_library.db_list_task_events", new=AsyncMock(return_value=[])
            ):
                client = TestClient(app)
                with client.stream(
                    "POST",
                    "/api/question-library/generate",
                    json={
                        "subject": "高中数学",
                        "topic": "导数",
                        "count": 1,
                        "mode": "standard",
                        "stream_reasoning": True,
                        "task_id": "ql-gen-session-1",
                    },
                ) as resp:
                    body = "\n".join(resp.iter_lines())

                self.assertEqual(resp.status_code, 200)
                self.assertIn('"session_id"', body)

                done_line = next((line for line in body.splitlines() if '"type": "done"' in line), "")
                self.assertTrue(done_line)
                payload = done_line.split("data: ", 1)[1]
                done_event = __import__("json").loads(payload)
                session_id = str(done_event["data"]["session_id"])
                preview_id = str(done_event["data"]["preview_id"])

                session_resp = client.get(f"/api/question-library/sessions/{session_id}")
                self.assertEqual(session_resp.status_code, 200)
                session_data = session_resp.json()["session"]
                self.assertEqual(session_data["session_id"], session_id)
                self.assertEqual(session_data["status"], "pending_review")
                self.assertEqual(len(session_data["draft_questions"]), 1)

                discard_resp = client.post(f"/api/question-library/previews/{preview_id}/discard")
                self.assertEqual(discard_resp.status_code, 200)

                session_after_discard = client.get(f"/api/question-library/sessions/{session_id}")
                self.assertEqual(session_after_discard.status_code, 200)
                self.assertEqual(session_after_discard.json()["session"]["status"], "archived_discarded")
        finally:
            preview_store._PREVIEWS_DIR = original_previews
            if original_sessions is not None:
                preview_store._SESSIONS_DIR = original_sessions
            app.dependency_overrides.clear()
            tmp.cleanup()

    def test_generate_append_merges_new_drafts_into_existing_session(self) -> None:
        app = create_app()
        self._override_auth(app)
        tmp, original_previews, original_sessions = self._with_temp_preview_dirs()
        try:
            if hasattr(preview_store, "save_session"):
                preview_store.save_session(
                    {
                        "session_id": "sess-append-1",
                        "user_id": "u-1",
                        "status": "pending_review",
                        "mode": "infinite",
                        "subject": "高中数学",
                        "topic": "导数",
                        "task_ids": ["task-old"],
                        "draft_questions": [
                            {
                                "question_id": "ai_old_1",
                                "stem": "旧题干",
                                "answer": "旧答案",
                                "analysis": "旧解析",
                                "review_status": "approved",
                            }
                        ],
                    }
                )
            preview_store.save_preview(
                {
                    "preview_id": "pv-append-1",
                    "session_id": "sess-append-1",
                    "status": "pending_review",
                    "user_id": "u-1",
                    "task_id": "task-old",
                    "subject": "高中数学",
                    "topic": "导数",
                    "draft_questions": [{"question_id": "ai_old_1", "stem": "旧题干", "answer": "旧答案", "analysis": "旧解析"}],
                }
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
                new=AsyncMock(return_value=[{"stem": "新题干", "answer": "新答案", "analysis": "新解析"}]),
            ), patch("backend.api.question_library.db_upsert_task", new=AsyncMock()), patch(
                "backend.api.question_library.db_append_task_event", new=AsyncMock()
            ), patch("backend.api.question_library.db_update_task_status", new=AsyncMock()), patch(
                "backend.api.question_library.db_list_task_events", new=AsyncMock(return_value=[])
            ):
                client = TestClient(app)
                with client.stream(
                    "POST",
                    "/api/question-library/generate",
                    json={
                        "subject": "高中数学",
                        "topic": "导数",
                        "count": 1,
                        "mode": "infinite",
                        "session_id": "sess-append-1",
                        "append": True,
                        "task_id": "ql-gen-append-1",
                    },
                ) as resp:
                    body = "\n".join(resp.iter_lines())
                self.assertEqual(resp.status_code, 200)
                self.assertIn('"session_id": "sess-append-1"', body)

                session_resp = client.get("/api/question-library/sessions/sess-append-1")
                self.assertEqual(session_resp.status_code, 200)
                draft_questions = session_resp.json()["session"]["draft_questions"]
                self.assertEqual(len(draft_questions), 2)
        finally:
            preview_store._PREVIEWS_DIR = original_previews
            if original_sessions is not None:
                preview_store._SESSIONS_DIR = original_sessions
            app.dependency_overrides.clear()
            tmp.cleanup()

    def test_commit_requires_review_approval_and_persists_review_state(self) -> None:
        app = create_app()
        self._override_auth(app)
        tmp, original_previews, original_sessions = self._with_temp_preview_dirs()
        try:
            preview_store.save_preview(
                {
                    "preview_id": "pv-review-1",
                    "session_id": "sess-review-1",
                    "status": "pending_review",
                    "user_id": "u-1",
                    "task_id": "task-review-1",
                    "subject": "高中数学",
                    "topic": "导数",
                    "draft_questions": [
                        {
                            "question_id": "q-1",
                            "stem": "题干",
                            "answer": "答案",
                            "analysis": "解析",
                            "review_status": "pending_review",
                        }
                    ],
                }
            )
            if hasattr(preview_store, "save_session"):
                preview_store.save_session(
                    {
                        "session_id": "sess-review-1",
                        "user_id": "u-1",
                        "status": "pending_review",
                        "subject": "高中数学",
                        "topic": "导数",
                        "preview_id": "pv-review-1",
                        "draft_questions": [
                            {
                                "question_id": "q-1",
                                "stem": "题干",
                                "answer": "答案",
                                "analysis": "解析",
                                "review_status": "pending_review",
                            }
                        ],
                    }
                )

            client = TestClient(app)
            blocked = client.post(
                "/api/question-library/previews/pv-review-1/commit",
                json={"questions": [{"question_id": "q-1", "stem": "题干", "answer": "答案", "analysis": "解析", "keep": True}]},
            )
            self.assertIn(blocked.status_code, {400, 409})

            with patch("backend.api.question_library.evaluate_generated_question_review", new=AsyncMock(return_value={
                "verdict": "好题",
                "overall_score": 88,
                "dimensions": [{"name": "思维含量", "score": 9, "comment": "好"}],
                "highlights": ["亮点"],
                "issues": [],
                "summary": "可通过",
                "model": "test-model",
            })), patch("backend.api.question_library.upsert_question_cache", new=AsyncMock()), patch(
                "backend.api.question_library.upsert_question_library_items", new=AsyncMock()
            ):
                review_resp = client.post("/api/question-library/sessions/sess-review-1/questions/q-1/review")
                self.assertEqual(review_resp.status_code, 200)

                approve_resp = client.post("/api/question-library/sessions/sess-review-1/questions/q-1/approve")
                self.assertEqual(approve_resp.status_code, 200)

                allowed = client.post(
                    "/api/question-library/previews/pv-review-1/commit",
                    json={"questions": [{"question_id": "q-1", "stem": "题干", "answer": "答案", "analysis": "解析", "keep": True}]},
                )
                self.assertEqual(allowed.status_code, 200)

                session_resp = client.get("/api/question-library/sessions/sess-review-1")
                self.assertEqual(session_resp.status_code, 200)
                self.assertEqual(session_resp.json()["session"]["status"], "committed")
        finally:
            preview_store._PREVIEWS_DIR = original_previews
            if original_sessions is not None:
                preview_store._SESSIONS_DIR = original_sessions
            app.dependency_overrides.clear()
            tmp.cleanup()

    def test_generate_stream_replays_reasoning_deltas_in_session_detail(self) -> None:
        app = create_app()
        self._override_auth(app)
        tmp, original_previews, original_sessions = self._with_temp_preview_dirs()
        try:
            async def fake_generate_questions(**kwargs):
                on_stage_event = kwargs.get("on_stage_event")
                on_reasoning_event = kwargs.get("on_reasoning_event")
                if on_stage_event:
                    await on_stage_event({"phase": "spec_search", "label": "规格搜索", "progress": 20, "stats": {"kept_specs": 1}})
                if on_reasoning_event:
                    await on_reasoning_event(
                        {
                            "type": "reasoning_delta",
                            "stage_id": "draft_realization",
                            "stage_label": "草稿生成",
                            "source": "raw",
                            "content": "先构造一个更有区分度的导数大题。",
                        }
                    )
                return [{"stem": "题干-带 reasoning", "answer": "答案", "analysis": "解析"}]

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
                "backend.api.question_library.generate_questions", new=AsyncMock(side_effect=fake_generate_questions)
            ), patch("backend.api.question_library.db_upsert_task", new=AsyncMock()), patch(
                "backend.api.question_library.db_append_task_event", new=AsyncMock()
            ), patch("backend.api.question_library.db_update_task_status", new=AsyncMock()), patch(
                "backend.api.question_library.db_list_task_events",
                new=AsyncMock(return_value=[{"taskId": "ql-gen-reason-1", "seq": 3, "type": "reasoning_delta", "data": {"content": "先构造一个更有区分度的导数大题。"}}]),
            ):
                client = TestClient(app)
                with client.stream(
                    "POST",
                    "/api/question-library/generate",
                    json={
                        "subject": "高中数学",
                        "topic": "导数",
                        "count": 1,
                        "stream_reasoning": True,
                        "task_id": "ql-gen-reason-1",
                    },
                ) as resp:
                    body = "\n".join(resp.iter_lines())

                self.assertEqual(resp.status_code, 200)
                self.assertIn('"reasoning_delta"', body)

                done_line = next((line for line in body.splitlines() if '"type": "done"' in line), "")
                payload = done_line.split("data: ", 1)[1]
                done_event = __import__("json").loads(payload)
                session_id = str(done_event["data"]["session_id"])

                session_resp = client.get(f"/api/question-library/sessions/{session_id}")
                self.assertEqual(session_resp.status_code, 200)
                session_data = session_resp.json()["session"]
                self.assertTrue(session_data["reasoning_blocks"])
                self.assertTrue(session_data["task_events"])
        finally:
            preview_store._PREVIEWS_DIR = original_previews
            if original_sessions is not None:
                preview_store._SESSIONS_DIR = original_sessions
            app.dependency_overrides.clear()
            tmp.cleanup()

    def test_subject_knowledge_tree_endpoint_returns_unified_nodes(self) -> None:
        app = create_app()
        self._override_auth(app)
        client = TestClient(app)
        resp = client.get("/api/subjects/高中数学/knowledge-tree?grade_id=1&textbook_version_id=1")
        app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("nodes", data)
        self.assertIsInstance(data["nodes"], list)

    def test_generate_stream_preserves_llm_request_failed_details(self) -> None:
        app = create_app()
        self._override_auth(app)

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
