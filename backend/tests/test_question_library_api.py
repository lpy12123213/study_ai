import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.api.auth import require_auth
from backend.app import create_app
from backend.generation.question_library import preview_store


def _passed_intuition_packet() -> dict:
    return {
        "version": "1.0",
        "validation": {
            "status": "passed",
            "scope_ok": True,
            "answer_correct": True,
            "answer_analysis_consistent": True,
            "conditions_sufficient": True,
            "unambiguous": True,
            "transfer_valid": True,
            "intuition_aligned": True,
            "structural_depth": True,
            "request_aligned": True,
            "issues": [],
            "repaired": False,
        },
    }


class TestQuestionLibraryApi(unittest.TestCase):
    def setUp(self) -> None:
        self._runtime_patch = patch.dict("os.environ", {"AGENT_RUNTIME": "legacy"}, clear=False)
        self._runtime_patch.start()
        self._reference_patch = patch(
            "backend.generation.question_library.runner.collect_reference_questions",
            new=AsyncMock(return_value={"questions": []}),
        )
        self._reference_patch.start()

    def tearDown(self) -> None:
        self._reference_patch.stop()
        self._runtime_patch.stop()

    def _override_auth(self, app) -> None:
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}

    def _with_temp_preview_dirs(self):
        base_dir = Path(__file__).resolve().parents[2] / ".local" / "test_tmp"
        base_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = base_dir / f"question-library-api-{uuid.uuid4().hex[:12]}"
        tmp_path.mkdir(parents=True, exist_ok=True)

        class _TmpDir:
            def __init__(self, path: Path) -> None:
                self.name = str(path)

            def cleanup(self) -> None:
                shutil.rmtree(self.name, ignore_errors=True)

        tmpdir = _TmpDir(tmp_path)
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

    def test_list_items_forwards_local_filter_params(self) -> None:
        app = create_app()
        self._override_auth(app)
        mock_list = AsyncMock(
            return_value={"success": True, "total": 0, "include_total": True, "items": [], "limit": 80, "offset": 0}
        )
        try:
            client = TestClient(app)
            with patch("backend.api.question_library.list_question_library_items", new=mock_list):
                resp = client.get(
                    "/api/question-library/items",
                    params={
                        "subject": "高中数学",
                        "origin": "crawled",
                        "area": "gaokao",
                        "hidden": "0",
                        "q": "函数",
                        "exam_scene": "期末",
                        "question_type": "单选题",
                        "difficulty": "容易",
                        "category": "新文化题",
                        "year": "2024",
                        "region": "北京",
                        "paper_name": "北京卷",
                        "question_number": "11",
                        "grade": "高三",
                        "semester": "期末",
                        "method": "分类讨论",
                        "only_new": "true",
                        "limit": "80",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 200)
        mock_list.assert_awaited_once()
        kwargs = mock_list.await_args.kwargs
        self.assertEqual(kwargs["user_id"], "u-1")
        self.assertEqual(kwargs["area"], "gaokao")
        self.assertEqual(kwargs["exam_scene"], "期末")
        self.assertEqual(kwargs["question_type"], "单选题")
        self.assertEqual(kwargs["difficulty"], "容易")
        self.assertEqual(kwargs["category"], "新文化题")
        self.assertEqual(kwargs["year"], "2024")
        self.assertEqual(kwargs["region"], "北京")
        self.assertEqual(kwargs["paper_name"], "北京卷")
        self.assertEqual(kwargs["question_number"], "11")
        self.assertEqual(kwargs["grade"], "高三")
        self.assertEqual(kwargs["semester"], "期末")
        self.assertEqual(kwargs["method"], "分类讨论")
        self.assertIs(kwargs["only_new"], True)

    def test_gaokao_import_endpoint_forwards_question_and_source(self) -> None:
        app = create_app()
        self._override_auth(app)
        mock_import = AsyncMock(return_value={"upserted": 1, "question_ids": ["gk-2024-1"]})
        payload = {
            "items": [
                {
                    "question_id": "gk-2024-1",
                    "subject": "高中数学",
                    "stem": "真题题干",
                    "answer": "A",
                    "source": {
                        "exam_year": 2024,
                        "region": "全国",
                        "paper_name": "2024年新课标I卷数学",
                        "paper_variant": "新课标I卷",
                        "question_number": "1",
                        "source_url": "https://example.test/gaokao.pdf",
                        "verified": True,
                    },
                }
            ]
        }
        try:
            client = TestClient(app)
            with patch("backend.api.question_library.upsert_gaokao_questions", new=mock_import):
                resp = client.post("/api/question-library/gaokao/items/manual-import", json=payload)
        finally:
            app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["question_ids"], ["gk-2024-1"])
        kwargs = mock_import.await_args.kwargs
        self.assertEqual(kwargs["user_id"], "u-1")
        self.assertEqual(kwargs["items"][0]["source"]["paper_name"], "2024年新课标I卷数学")

    def test_gaokao_import_rejects_missing_provenance(self) -> None:
        app = create_app()
        self._override_auth(app)
        try:
            client = TestClient(app)
            resp = client.post(
                "/api/question-library/gaokao/items/manual-import",
                json={"items": [{"question_id": "gk-1", "subject": "高中数学", "stem": "题干"}]},
            )
        finally:
            app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 422)

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
                    "difficulty": "困难",
                    "question_type": "解答题",
                    "use_study_archive": True,
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
        self.assertEqual(data["preview"]["difficulty"], "困难")
        self.assertEqual(data["preview"]["question_type"], "解答题")
        self.assertTrue(data["preview"]["use_study_archive"])

    def test_generate_creates_persisted_session_and_discard_archives_it(self) -> None:
        app = create_app()
        self._override_auth(app)
        requested_topic = "导数\n第二行硬约束：迁移必须改变边界或表征，不能只换数字。"
        captured_source_packs: list[dict] = []
        llm_source_pack = {
            "subject": "高中数学",
            "topic": "导数",
            "study_markdown": "",
            "facts": [],
            "skills": [],
            "common_mistakes": [],
            "forbidden_patterns": [],
        }
        candidates = [
            {
                "question_id": f"candidate-{index}",
                "stem": f"题干 {index}",
                "answer": f"答案 {index}",
                "analysis": f"解析 {index}",
            }
            for index in range(1, 4)
        ]

        async def fake_generate_questions(**kwargs):
            captured_source_packs.append(dict(kwargs.get("source_pack") or {}))
            callback = kwargs.get("on_candidate_accepted")
            if callable(callback):
                for candidate in candidates:
                    await callback(candidate)
            # Simulate select_final choosing only one of three accepted
            # candidates for a standard count=1 request.
            return [candidates[1]]

        tmp, original_previews, original_sessions = self._with_temp_preview_dirs()
        try:
            with patch("backend.generation.question_library.runner.is_llm_configured", return_value=True), patch(
                "backend.generation.question_library.runner.build_source_pack", new=AsyncMock(return_value=llm_source_pack)
            ), patch(
                "backend.generation.question_library.runner.build_curriculum_context", new=AsyncMock(return_value={})
            ), patch(
                "backend.generation.question_library.runner.generate_questions",
                new=AsyncMock(side_effect=fake_generate_questions),
            ), patch("backend.shared.tasks.db_store.db_upsert_task", new=AsyncMock()), patch(
                "backend.shared.tasks.db_store.db_append_task_event", new=AsyncMock()
            ), patch("backend.shared.tasks.db_store.db_update_task_status", new=AsyncMock()), patch(
                "backend.generation.question_library.session_service.db_list_task_events", new=AsyncMock(return_value=[])
            ):
                client = TestClient(app)
                with client.stream(
                    "POST",
                    "/api/question-library/generate",
                    json={
                        "subject": "高中数学",
                        "topic": requested_topic,
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
                self.assertEqual(done_event["data"]["count"], 1)
                self.assertEqual(captured_source_packs[0]["topic"], "导数")
                self.assertEqual(captured_source_packs[0]["requested_topic"], requested_topic)

                session_resp = client.get(f"/api/question-library/sessions/{session_id}")
                self.assertEqual(session_resp.status_code, 200)
                session_data = session_resp.json()["session"]
                self.assertEqual(session_data["session_id"], session_id)
                self.assertEqual(session_data["status"], "pending_review")
                self.assertEqual(session_data["topic"], requested_topic)
                self.assertEqual(len(session_data["draft_questions"]), 1)
                self.assertEqual(session_data["draft_questions"][0]["stem"], "题干 2")

                preview_data = preview_store.load_preview(preview_id)
                self.assertIsInstance(preview_data, dict)
                self.assertEqual(len(preview_data["draft_questions"]), 1)
                self.assertEqual(preview_data["draft_questions"][0]["stem"], "题干 2")

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

            async def fake_generate_questions(*args, **kwargs):  # type: ignore[no-untyped-def]
                _ = args
                callback = kwargs.get("on_candidate_accepted")
                if callable(callback):
                    await callback(
                        {
                            "question_id": "candidate-not-selected",
                            "stem": "临时候选题干",
                            "answer": "临时候选答案",
                            "analysis": "临时候选解析",
                        }
                    )
                session = preview_store.load_session("sess-append-1") or {}
                session["stop_requested"] = True
                preview_store.save_session(session)
                return [{"stem": "新题干", "answer": "新答案", "analysis": "新解析"}]

            with patch("backend.generation.question_library.runner.is_llm_configured", return_value=True), patch(
                "backend.generation.question_library.runner.build_source_pack",
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
                "backend.generation.question_library.runner.build_curriculum_context", new=AsyncMock(return_value={})
            ), patch(
                "backend.generation.question_library.runner.generate_questions",
                new=AsyncMock(side_effect=fake_generate_questions),
            ), patch("backend.shared.tasks.db_store.db_upsert_task", new=AsyncMock()), patch(
                "backend.shared.tasks.db_store.db_append_task_event", new=AsyncMock()
            ), patch("backend.shared.tasks.db_store.db_update_task_status", new=AsyncMock()), patch(
                "backend.generation.question_library.session_service.db_list_task_events", new=AsyncMock(return_value=[])
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
                session_data = session_resp.json()["session"]
                draft_questions = session_data["draft_questions"]
                self.assertEqual(len(draft_questions), 2)
                self.assertEqual({item["stem"] for item in draft_questions}, {"旧题干", "新题干"})
                self.assertEqual(session_data["count"], 2)
                self.assertEqual(session_data["requested_count"], 1)
                self.assertEqual(session_data["draft_count"], 2)

                preview_resp = client.get("/api/question-library/previews/pv-append-1")
                self.assertEqual(preview_resp.status_code, 200)
                preview_data = preview_resp.json()
                self.assertEqual(preview_data["count"], 2)
                self.assertEqual(preview_data["requested_count"], 1)
                self.assertEqual(preview_data["draft_count"], 2)

                sessions_resp = client.get("/api/question-library/sessions")
                self.assertEqual(sessions_resp.status_code, 200)
                summary = next(
                    item for item in sessions_resp.json()["sessions"] if item["session_id"] == "sess-append-1"
                )
                self.assertEqual(summary["count"], 2)
                self.assertEqual(summary["requested_count"], 1)
                self.assertEqual(summary["draft_count"], 2)
        finally:
            preview_store._PREVIEWS_DIR = original_previews
            if original_sessions is not None:
                preview_store._SESSIONS_DIR = original_sessions
            app.dependency_overrides.clear()
            tmp.cleanup()

    def test_generate_infinite_mode_retries_batches_until_stop_requested(self) -> None:
        app = create_app()
        self._override_auth(app)
        tmp, original_previews, original_sessions = self._with_temp_preview_dirs()
        try:
            generate_calls = 0

            async def fake_generate_questions(*args, **kwargs):  # type: ignore[no-untyped-def]
                nonlocal generate_calls
                _ = args
                generate_calls += 1
                callback = kwargs.get("on_candidate_accepted")
                if callable(callback):
                    await callback(
                        {
                            "question_id": f"transient-{generate_calls}",
                            "stem": f"临时候选 {generate_calls}",
                            "answer": "临时候选答案",
                            "analysis": "临时候选解析",
                        }
                    )
                if generate_calls == 1:
                    raise RuntimeError("batch_boom")
                if generate_calls == 2:
                    return []
                session = preview_store.load_session("sess-infinite-1") or {}
                session["stop_requested"] = True
                preview_store.save_session(session)
                return [{"stem": "最终题干", "answer": "最终答案", "analysis": "最终解析"}]

            with patch("backend.generation.question_library.runner.is_llm_configured", return_value=True), patch(
                "backend.generation.question_library.runner.build_source_pack",
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
                "backend.generation.question_library.runner.build_curriculum_context", new=AsyncMock(return_value={})
            ), patch(
                "backend.generation.question_library.runner.generate_questions",
                new=AsyncMock(side_effect=fake_generate_questions),
            ), patch("backend.generation.question_library.runner.asyncio.sleep", new=AsyncMock()), patch(
                "backend.shared.tasks.db_store.db_upsert_task", new=AsyncMock()
            ), patch("backend.shared.tasks.db_store.db_append_task_event", new=AsyncMock()), patch(
                "backend.shared.tasks.db_store.db_update_task_status", new=AsyncMock()
            ), patch("backend.generation.question_library.session_service.db_list_task_events", new=AsyncMock(return_value=[])):
                client = TestClient(app)
                with client.stream(
                    "POST",
                    "/api/question-library/generate",
                    json={
                        "subject": "高中数学",
                        "topic": "导数",
                        "count": 1,
                        "mode": "infinite",
                        "session_id": "sess-infinite-1",
                        "task_id": "ql-gen-infinite-1",
                    },
                ) as resp:
                    body = "\n".join(resp.iter_lines())

                self.assertEqual(resp.status_code, 200)
                self.assertGreaterEqual(generate_calls, 3)
                self.assertIn('"type": "done"', body)

                session_resp = client.get("/api/question-library/sessions/sess-infinite-1")
                self.assertEqual(session_resp.status_code, 200)
                session_data = session_resp.json()["session"]
                self.assertEqual(session_data["status"], "stopped")
                self.assertEqual(len(session_data["draft_questions"]), 1)
                self.assertEqual(session_data["draft_questions"][0]["stem"], "最终题干")
        finally:
            preview_store._PREVIEWS_DIR = original_previews
            if original_sessions is not None:
                preview_store._SESSIONS_DIR = original_sessions
            app.dependency_overrides.clear()
            tmp.cleanup()

    def test_approve_auto_commits_single_question_and_keeps_remaining_drafts_pending(self) -> None:
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
                            "intuition_packet": _passed_intuition_packet(),
                            "review_status": "pending_review",
                        },
                        {
                            "question_id": "q-2",
                            "stem": "题干2",
                            "answer": "答案2",
                            "analysis": "解析2",
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
                                "intuition_packet": _passed_intuition_packet(),
                                "review_status": "pending_review",
                            },
                            {
                                "question_id": "q-2",
                                "stem": "题干2",
                                "answer": "答案2",
                                "analysis": "解析2",
                                "review_status": "pending_review",
                            }
                        ],
                    }
                )

            client = TestClient(app)
            with patch("backend.generation.question_library.session_service.evaluate_generated_question_review", new=AsyncMock(return_value={
                "verdict": "好题",
                "overall_score": 88,
                "dimensions": [{"name": "思维含量", "score": 9, "comment": "好"}],
                "highlights": ["亮点"],
                "issues": [],
                "summary": "可通过",
                "model": "test-model",
            })), patch("backend.generation.question_library.session_service.upsert_question_cache", new=AsyncMock()) as cache_mock, patch(
                "backend.generation.question_library.session_service.upsert_question_library_items", new=AsyncMock()
            ):
                approve_resp = client.post("/api/question-library/sessions/sess-review-1/questions/q-1/approve")
                self.assertEqual(approve_resp.status_code, 200)
                self.assertEqual(approve_resp.json()["question"]["review_status"], "committed")
                cache_mock.assert_awaited_once()

                session_resp = client.get("/api/question-library/sessions/sess-review-1")
                self.assertEqual(session_resp.status_code, 200)
                session_data = session_resp.json()["session"]
                self.assertEqual(session_data["status"], "pending_review")
                q1 = next(item for item in session_data["draft_questions"] if item["question_id"] == "q-1")
                q2 = next(item for item in session_data["draft_questions"] if item["question_id"] == "q-2")
                self.assertEqual(q1["review_status"], "committed")
                self.assertEqual(q2["review_status"], "pending_review")
                self.assertIn("q-1", session_data["confirmed_question_ids"])
        finally:
            preview_store._PREVIEWS_DIR = original_previews
            if original_sessions is not None:
                preview_store._SESSIONS_DIR = original_sessions
            app.dependency_overrides.clear()
            tmp.cleanup()

    def test_confirm_auto_commits_without_separate_batch_commit(self) -> None:
        app = create_app()
        self._override_auth(app)
        tmp, original_previews, original_sessions = self._with_temp_preview_dirs()
        try:
            preview_store.save_preview(
                {
                    "preview_id": "pv-confirm-1",
                    "session_id": "sess-confirm-1",
                    "status": "pending_review",
                    "user_id": "u-1",
                    "task_id": "task-confirm-1",
                    "subject": "高中数学",
                    "topic": "数列",
                    "draft_questions": [
                        {
                            "question_id": "q-1",
                            "stem": "题干",
                            "answer": "答案",
                            "analysis": "解析",
                            "intuition_packet": _passed_intuition_packet(),
                            "review_status": "pending_review",
                        }
                    ],
                }
            )
            if hasattr(preview_store, "save_session"):
                preview_store.save_session(
                    {
                        "session_id": "sess-confirm-1",
                        "user_id": "u-1",
                        "status": "pending_review",
                        "subject": "高中数学",
                        "topic": "数列",
                        "preview_id": "pv-confirm-1",
                        "draft_questions": [
                            {
                                "question_id": "q-1",
                                "stem": "题干",
                                "answer": "答案",
                                "analysis": "解析",
                                "intuition_packet": _passed_intuition_packet(),
                                "review_status": "pending_review",
                            }
                        ],
                    }
                )

            client = TestClient(app)
            with patch("backend.generation.question_library.session_service.evaluate_generated_question_review", new=AsyncMock(return_value={
                "verdict": "好题",
                "overall_score": 90,
                "dimensions": [],
                "highlights": ["亮点"],
                "issues": [],
                "summary": "可通过",
                "model": "test-model",
            })), patch("backend.generation.question_library.session_service.upsert_question_cache", new=AsyncMock()) as cache_mock, patch(
                "backend.generation.question_library.session_service.upsert_question_library_items", new=AsyncMock()
            ) as lib_mock:
                confirm_resp = client.post("/api/question-library/sessions/sess-confirm-1/questions/q-1/confirm")
                self.assertEqual(confirm_resp.status_code, 200)
                self.assertEqual(confirm_resp.json()["question"]["review_status"], "committed")
                cache_mock.assert_awaited_once()
                lib_mock.assert_awaited_once()

                session_resp = client.get("/api/question-library/sessions/sess-confirm-1")
                self.assertEqual(session_resp.status_code, 200)
                self.assertEqual(session_resp.json()["session"]["status"], "committed")
        finally:
            preview_store._PREVIEWS_DIR = original_previews
            if original_sessions is not None:
                preview_store._SESSIONS_DIR = original_sessions
            app.dependency_overrides.clear()
            tmp.cleanup()

    def test_confirm_rejects_legacy_packet_missing_new_hard_gates(self) -> None:
        app = create_app()
        self._override_auth(app)
        tmp, original_previews, original_sessions = self._with_temp_preview_dirs()
        try:
            legacy_packet = _passed_intuition_packet()
            legacy_packet["validation"].pop("intuition_aligned")
            legacy_packet["validation"].pop("structural_depth")
            legacy_packet["validation"].pop("request_aligned")
            preview_store.save_session(
                {
                    "session_id": "sess-legacy-gate-1",
                    "user_id": "u-1",
                    "status": "pending_review",
                    "subject": "高中数学",
                    "topic": "数列",
                    "draft_questions": [
                        {
                            "question_id": "q-legacy",
                            "stem": "旧题干",
                            "answer": "旧答案",
                            "analysis": "旧解析",
                            "intuition_packet": legacy_packet,
                            "review": {"verdict": "可练习"},
                            "review_status": "pending_review",
                        }
                    ],
                }
            )

            client = TestClient(app)
            with patch(
                "backend.generation.question_library.session_service.upsert_question_cache", new=AsyncMock()
            ) as cache_mock, patch(
                "backend.generation.question_library.session_service.upsert_question_library_items", new=AsyncMock()
            ):
                response = client.post(
                    "/api/question-library/sessions/sess-legacy-gate-1/questions/q-legacy/confirm"
                )

            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"], "intuition_validation_failed")
            cache_mock.assert_not_awaited()
        finally:
            preview_store._PREVIEWS_DIR = original_previews
            if original_sessions is not None:
                preview_store._SESSIONS_DIR = original_sessions
            app.dependency_overrides.clear()
            tmp.cleanup()

    def test_batch_commit_rejects_content_changed_after_validation(self) -> None:
        app = create_app()
        self._override_auth(app)
        tmp, original_previews, original_sessions = self._with_temp_preview_dirs()
        try:
            preview_store.save_preview(
                {
                    "preview_id": "pv-tamper-1",
                    "session_id": "sess-tamper-1",
                    "status": "pending_review",
                    "user_id": "u-1",
                    "subject": "高中数学",
                    "topic": "等差数列",
                    "difficulty": "中等",
                    "question_type": "解答题",
                    "draft_questions": [
                        {
                            "question_id": "q-tamper",
                            "stem": "已校验题干",
                            "answer": "已校验答案",
                            "analysis": "已校验解析",
                            "intuition_packet": _passed_intuition_packet(),
                            "review_status": "pending_review",
                        }
                    ],
                }
            )

            client = TestClient(app)
            with patch(
                "backend.generation.question_library.session_service.upsert_question_cache", new=AsyncMock()
            ) as cache_mock, patch(
                "backend.generation.question_library.session_service.upsert_question_library_items", new=AsyncMock()
            ):
                response = client.post(
                    "/api/question-library/previews/pv-tamper-1/commit",
                    json={
                        "questions": [
                            {
                                "question_id": "q-tamper",
                                "stem": "篡改后的机械套公式题",
                                "answer": "已校验答案",
                                "analysis": "已校验解析",
                                "keep": True,
                            }
                        ]
                    },
                )

            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"], "question_content_changed_after_validation")
            cache_mock.assert_not_awaited()
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

            with patch("backend.generation.question_library.runner.is_llm_configured", return_value=True), patch(
                "backend.generation.question_library.runner.build_source_pack",
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
                "backend.generation.question_library.runner.generate_questions", new=AsyncMock(side_effect=fake_generate_questions)
            ), patch("backend.shared.tasks.db_store.db_upsert_task", new=AsyncMock()), patch(
                "backend.shared.tasks.db_store.db_append_task_event", new=AsyncMock()
            ), patch("backend.shared.tasks.db_store.db_update_task_status", new=AsyncMock()), patch(
                "backend.generation.question_library.session_service.db_list_task_events",
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
        fake_crawler = AsyncMock()
        fake_crawler.get_knowledge_tree = AsyncMock(
            return_value={
                "success": True,
                "nodes": [
                    {
                        "id": "root",
                        "label": "高中数学知识点",
                        "type": "root",
                        "children": [],
                    }
                ],
            }
        )
        fake_crawler.get_available_filters = AsyncMock(
            return_value={
                "grades": [{"id": 1, "name": "高一"}],
                "textbook_versions": [{"id": 1, "name": "人教版"}],
            }
        )
        try:
            client = TestClient(app)
            with patch("backend.api.subjects.get_crawler", new=AsyncMock(return_value=fake_crawler)):
                resp = client.get("/api/subjects/高中数学/knowledge-tree?grade_id=1&textbook_version_id=1")
        finally:
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

        with patch("backend.generation.question_library.runner.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.runner.build_source_pack",
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
            "backend.generation.question_library.runner.generate_questions",
            new=AsyncMock(side_effect=RuntimeError(llm_error)),
        ), patch("backend.shared.tasks.db_store.db_upsert_task", new=AsyncMock()), patch(
            "backend.shared.tasks.db_store.db_append_task_event", new=AsyncMock()
        ), patch("backend.shared.tasks.db_store.db_update_task_status", new=AsyncMock()):
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

    def test_generate_preserves_partial_drafts_when_pipeline_errors_after_accepting_candidates(self) -> None:
        app = create_app()
        self._override_auth(app)
        tmp, original_previews, original_sessions = self._with_temp_preview_dirs()
        try:
            async def fake_generate_questions(**kwargs):
                callback = kwargs.get("on_candidate_accepted")
                if callable(callback):
                    for index in range(3):
                        maybe_result = callback(
                            {
                                "stem": f"中途保留题干 {index + 1}",
                                "answer": f"中途保留答案 {index + 1}",
                                "analysis": f"中途保留解析 {index + 1}",
                                "question_id": f"accepted-{index + 1}",
                                "skill": "分类讨论",
                                "reasoning": "多步推导",
                                "surface": "综合题",
                            }
                        )
                        if hasattr(maybe_result, "__await__"):
                            await maybe_result
                raise RuntimeError("judge_stage_boom")

            with patch("backend.generation.question_library.runner.is_llm_configured", return_value=True), patch(
                "backend.generation.question_library.runner.build_source_pack",
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
                "backend.generation.question_library.runner.build_curriculum_context", new=AsyncMock(return_value={})
            ), patch(
                "backend.generation.question_library.runner.generate_questions", new=AsyncMock(side_effect=fake_generate_questions)
            ), patch("backend.shared.tasks.db_store.db_upsert_task", new=AsyncMock()), patch(
                "backend.shared.tasks.db_store.db_append_task_event", new=AsyncMock()
            ), patch("backend.shared.tasks.db_store.db_update_task_status", new=AsyncMock()), patch(
                "backend.generation.question_library.session_service.db_list_task_events", new=AsyncMock(return_value=[])
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
                        "task_id": "ql-gen-partial-1",
                    },
                ) as resp:
                    body = "\n".join(resp.iter_lines())

                self.assertEqual(resp.status_code, 200)
                self.assertIn("judge_stage_boom", body)

                session_files = list((preview_store._SESSIONS_DIR).glob("*.json"))
                self.assertTrue(session_files)
                session_obj = preview_store.load_session(session_files[0].stem)
                self.assertIsInstance(session_obj, dict)
                self.assertEqual(session_obj["status"], "partial_failure")
                self.assertEqual(len(session_obj["draft_questions"]), 1)
                self.assertEqual(session_obj["draft_questions"][0]["stem"], "中途保留题干 1")
        finally:
            preview_store._PREVIEWS_DIR = original_previews
            if original_sessions is not None:
                preview_store._SESSIONS_DIR = original_sessions
            app.dependency_overrides.clear()
            tmp.cleanup()
