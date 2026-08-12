from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.api.auth import require_auth
from backend.api.tasks import _set_historical_eta
from backend.app import create_app


class TestTasksApiContract(unittest.TestCase):
    def _override_auth(self, app) -> None:
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}

    def test_router_is_mounted(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/tasks")
        # Auth will block; we only assert that the router is mounted.
        self.assertNotEqual(resp.status_code, 404)

    def test_overdue_historical_eta_is_unknown_instead_of_zero(self) -> None:
        task = {"eta_s": 0.0}
        _set_historical_eta(task, elapsed_s=120.0, average_s=60.0)

        self.assertEqual(task["elapsed_s"], 120.0)
        self.assertNotIn("eta_s", task)
        self.assertTrue(task["eta_overdue"])

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

        with patch("backend.api.tasks.submit_knowledge_video_task", new=AsyncMock(return_value=dummy_task)):
            resp = client.post(
                "/api/tasks/knowledge-videos/generate",
                json={"topic": "导数的几何意义", "subject": "高中数学", "duration_seconds": 20},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"success": True, "taskId": "task-1"})

        with (
            patch(
                "backend.generation.study_materials.orchestrator_singleton.study_material_tasks.create_task",
                new=AsyncMock(return_value=dummy_task),
            ),
            patch(
                "backend.generation.study_materials.orchestrator_singleton.study_material_tasks.continue_task",
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
            patch("backend.generation.question_library.runner.create_crawl_task", new=AsyncMock(return_value=dummy_task)),
            patch("backend.generation.question_library.runner.create_generate_task", new=AsyncMock(return_value=dummy_task)),
            patch("backend.generation.question_library.runner.create_score_task", new=AsyncMock(return_value=dummy_task)),
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

    def test_deepthink_cancel_flow(self) -> None:
        """Canonical DeepThink 长任务闭环：提交 → 取消 → 状态对齐为 canceled。

        前端已迁移到 ``POST /api/tasks/deepthink`` 并显式调用取消 API，
        客户端断开不再隐含取消（见 backend/api/deepthink.py 兼容入口文档）。
        """

        app = create_app()
        self._override_auth(app)
        client = TestClient(app)

        dummy_task = SimpleNamespace(task_id="deepthink-1")

        with patch("backend.api.tasks.submit_deepthink_task", new=AsyncMock(return_value=dummy_task)):
            resp = client.post("/api/tasks/deepthink", json={"question": "1+1=?", "subject": "高中数学"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"success": True, "taskId": "deepthink-1"})

        canceled_task = {
            "id": "deepthink-1",
            "user_id": "u-1",
            "task_type": "deepthink",
            "title": "深度解题",
            "status": "canceled",
            "progress": 10,
        }

        with (
            patch("backend.api.tasks.task_runtime.cancel_task", new=AsyncMock(return_value=True)) as cancel,
            patch("backend.api.tasks.db_get_task", new=AsyncMock(return_value=canceled_task)) as get_task,
        ):
            cancel_resp = client.post("/api/tasks/deepthink-1/cancel")
            self.assertEqual(cancel_resp.status_code, 200)
            self.assertEqual(cancel_resp.json(), {"success": True})
            cancel.assert_awaited_once_with(task_id="deepthink-1", user_id="u-1")

            status_resp = client.get("/api/tasks/deepthink-1")
            self.assertEqual(status_resp.status_code, 200)
            self.assertEqual(status_resp.json()["status"], "canceled")
            get_task.assert_awaited()

        app.dependency_overrides.clear()

    def test_stream_endpoint_is_mounted(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/tasks/task-1/stream")
        # Auth will block; we only assert that it is not a missing route.
        self.assertNotEqual(resp.status_code, 404)

    def test_export_paper_task_preserves_split_bundle_flag(self) -> None:
        app = create_app()
        self._override_auth(app)
        client = TestClient(app)

        dummy_task = SimpleNamespace(task_id="task-1")

        with patch("backend.api.tasks.submit_export_paper_task", new=AsyncMock(return_value=dummy_task)) as submit:
            resp = client.post("/api/tasks/export/papers/1", json={"format": "markdown", "splitBundle": True})

        self.assertEqual(resp.status_code, 200)
        submit.assert_awaited_once()
        self.assertTrue(submit.await_args.kwargs["request"]["split_bundle"])
        app.dependency_overrides.clear()

    def test_get_task_status_can_include_persisted_events(self) -> None:
        app = create_app()
        self._override_auth(app)
        client = TestClient(app)

        get_task = AsyncMock(
            return_value={
                "id": "task-1",
                "user_id": "u-1",
                "task_type": "study_materials",
                "title": "导数资料",
                "status": "running",
                "progress": 40,
                "last_seq": 2,
                "events": [
                    {"taskId": "task-1", "seq": 1, "type": "step", "data": {"step": {"id": "s1"}}},
                    {"taskId": "task-1", "seq": 2, "type": "progress", "data": {"progress": 40}},
                ],
            }
        )

        with patch("backend.api.tasks.db_get_task", new=get_task):
            resp = client.get("/api/tasks/task-1?include_events=true&events_limit=25&events_after_seq=2")

        self.assertEqual(resp.status_code, 200)
        get_task.assert_awaited_once()
        kwargs = get_task.await_args.kwargs
        self.assertIs(kwargs["include_events"], True)
        self.assertEqual(kwargs["events_limit"], 25)
        self.assertEqual(kwargs["events_after_seq"], 2)
        self.assertEqual(resp.json()["events"][0]["seq"], 1)

        app.dependency_overrides.clear()

    def test_get_task_status_defaults_to_small_event_window(self) -> None:
        app = create_app()
        self._override_auth(app)
        client = TestClient(app)

        get_task = AsyncMock(
            return_value={
                "id": "task-1",
                "user_id": "u-1",
                "task_type": "study_materials",
                "title": "导数资料",
                "status": "completed",
                "progress": 100,
                "last_seq": 500,
                "events": [],
            }
        )

        with patch("backend.api.tasks.db_get_task", new=get_task):
            resp = client.get("/api/tasks/task-1?include_events=true")

        self.assertEqual(resp.status_code, 200)
        kwargs = get_task.await_args.kwargs
        self.assertEqual(kwargs["events_limit"], 200)
        self.assertEqual(kwargs["events_after_seq"], 0)

        app.dependency_overrides.clear()

    def test_resume_db_only_paused_task_rejects_when_runner_unavailable(self) -> None:
        """A paused task whose in-memory runner is gone (e.g. after a server
        restart) must not be silently flipped to running with no real runner.
        The endpoint should return ``task_runner_unavailable`` so the client
        can fall back to retry/continue flows instead of getting stuck.
        """

        app = create_app()
        self._override_auth(app)
        client = TestClient(app)

        get_task = AsyncMock(
            return_value={
                "id": "task-paused",
                "user_id": "u-1",
                "task_type": "study_materials",
                "title": "暂停任务",
                "status": "paused",
                "progress": 40,
            }
        )
        update_status = AsyncMock(return_value=True)
        append_event = AsyncMock(return_value={"seq": 3})

        with (
            patch("backend.api.tasks.task_runtime.resume_task", new=AsyncMock(return_value=False)),
            patch("backend.api.tasks.db_get_task", new=get_task),
            patch("backend.api.tasks.db_update_task_status", new=update_status),
            patch("backend.api.tasks.db_append_task_event", new=append_event),
        ):
            resp = client.post("/api/tasks/task-paused/resume")

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json().get("detail"), "task_runner_unavailable")
        update_status.assert_not_awaited()
        append_event.assert_not_awaited()

        app.dependency_overrides.clear()

    def test_resume_running_db_task_returns_success_without_db_writes(self) -> None:
        """Resuming a task already in ``running`` status should be a no-op success."""

        app = create_app()
        self._override_auth(app)
        client = TestClient(app)

        get_task = AsyncMock(
            return_value={
                "id": "task-running",
                "user_id": "u-1",
                "task_type": "study_materials",
                "title": "运行中",
                "status": "running",
                "progress": 20,
            }
        )
        update_status = AsyncMock(return_value=True)
        append_event = AsyncMock(return_value={"seq": 3})

        with (
            patch("backend.api.tasks.task_runtime.resume_task", new=AsyncMock(return_value=False)),
            patch("backend.api.tasks.db_get_task", new=get_task),
            patch("backend.api.tasks.db_update_task_status", new=update_status),
            patch("backend.api.tasks.db_append_task_event", new=append_event),
        ):
            resp = client.post("/api/tasks/task-running/resume")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"success": True})
        update_status.assert_not_awaited()
        append_event.assert_not_awaited()

        app.dependency_overrides.clear()

    def test_stream_replays_persisted_events_even_when_runtime_task_exists(self) -> None:
        app = create_app()
        self._override_auth(app)
        client = TestClient(app)

        runtime_task = SimpleNamespace(user_id="u-1")

        async def runtime_stream(*_args, **_kwargs):
            yield {"taskId": "task-1", "seq": 999, "type": "error", "data": {"error": "runtime_only"}}

        get_task = AsyncMock(
            return_value={
                "id": "task-1",
                "user_id": "u-1",
                "task_type": "study_materials",
                "title": "导数资料",
                "status": "completed",
                "progress": 100,
                "last_seq": 1,
            }
        )
        list_events = AsyncMock(
            return_value=[
                {"taskId": "task-1", "seq": 1, "type": "progress", "data": {"progress": 100, "source": "db"}}
            ]
        )

        with (
            patch("backend.api.tasks.task_runtime.get_task", new=AsyncMock(return_value=runtime_task)),
            patch("backend.api.tasks.task_runtime.stream", new=runtime_stream),
            patch("backend.api.tasks.db_get_task", new=get_task),
            patch("backend.api.tasks.db_list_task_events", new=list_events),
        ):
            resp = client.get("/api/tasks/task-1/stream?after_seq=0")

        self.assertEqual(resp.status_code, 200)
        text = resp.text
        self.assertIn('"seq": 1', text)
        self.assertIn('"source": "db"', text)
        self.assertNotIn("runtime_only", text)
        list_events.assert_awaited()

        app.dependency_overrides.clear()

    def test_retry_supports_each_question_library_task_type(self) -> None:
        app = create_app()
        self._override_auth(app)
        client = TestClient(app)

        cases = [
            ("question_library_crawl", "backend.generation.question_library.runner.create_crawl_task"),
            ("question_library_generate", "backend.generation.question_library.runner.create_generate_task"),
            ("question_library_score", "backend.generation.question_library.runner.create_score_task"),
            ("question_library_media_import", "backend.generation.question_library.runner.create_media_import_task"),
        ]

        for task_type, creator_path in cases:
            with self.subTest(task_type=task_type):
                stored_task = {
                    "id": f"orig-{task_type}",
                    "user_id": "u-1",
                    "task_type": task_type,
                    "request": {"subject": "高中数学"},
                }
                created = SimpleNamespace(task_id=f"retry-{task_type}")
                with (
                    patch("backend.api.tasks.db_get_task", new=AsyncMock(return_value=stored_task)),
                    patch(creator_path, new=AsyncMock(return_value=created)) as creator,
                ):
                    resp = client.post(f"/api/tasks/{stored_task['id']}/retry")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json(), {"success": True, "taskId": created.task_id})
                creator.assert_awaited_once()

        app.dependency_overrides.clear()

    def test_compose_review_saves_pending_review_draft(self) -> None:
        app = create_app()
        self._override_auth(app)
        client = TestClient(app)

        pending_task = {
            "id": "task-review",
            "user_id": "u-1",
            "task_type": "paper_compose",
            "title": "待审卷",
            "status": "pending_review",
            "events": [
                {
                    "taskId": "task-review",
                    "seq": 3,
                    "type": "pending_review",
                    "data": {
                        "composeDraft": {
                            "paperName": "待审卷",
                            "mode": "",
                            "questions": [
                                {
                                    "subject": "高中数学",
                                    "question_id": "q-review",
                                    "type": "解答题",
                                    "difficulty": "中等",
                                    "knowledge_point": "函数",
                                    "stem": "待审核草稿题干",
                                    "answer": "1",
                                    "analysis": "解析。",
                                    "quality_score": 90,
                                    "source": "zujuan",
                                },
                                {
                                    "subject": "高中数学",
                                    "question_id": "q-reject",
                                    "type": "选择题",
                                    "difficulty": "容易",
                                    "knowledge_point": "函数",
                                    "stem": "应剔除题干",
                                    "answer": "A",
                                    "analysis": "解析。",
                                    "quality_score": 20,
                                    "source": "ai",
                                }
                            ],
                        }
                    },
                }
            ],
        }
        saved_paper = {
            "paper_id": 88,
            "paper_name": "待审卷",
            "source_mode": "zujuan",
            "created_at": "2026-06-05T00:00:00Z",
            "questions": [
                {
                    "question_id": "q-review",
                    "order": 1,
                    "type": "解答题",
                    "difficulty": "中等",
                    "knowledge_point": "函数",
                    "source_url": "",
                    "stem": "   ",
                }
            ],
        }

        with (
            patch("backend.api.tasks.db_get_task", new=AsyncMock(return_value=pending_task)) as get_task,
            patch("backend.api.tasks.save_paper", new=AsyncMock(return_value=88)) as save,
            patch("backend.api.tasks.get_paper", new=AsyncMock(return_value=saved_paper)),
            patch("backend.api.tasks.db_append_task_event", new=AsyncMock(return_value=4)) as append_event,
            patch("backend.api.tasks.db_update_task_status", new=AsyncMock(return_value=True)) as update_status,
        ):
            resp = client.post(
                "/api/tasks/task-review/compose-review",
                json={
                    "questions": [
                        {"questionId": "q-review", "status": "approved", "stem": "   "},
                        {"questionId": "q-reject", "status": "rejected"},
                    ]
                },
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["paper"]["id"], 88)
        self.assertEqual(body["paper"]["questions"][0]["stem"], "待审核草稿题干")
        save.assert_awaited_once()
        saved_questions = save.await_args.kwargs["questions"]
        self.assertEqual([q["question_id"] for q in saved_questions], ["q-review"])
        self.assertEqual(saved_questions[0]["stem"], "待审核草稿题干")
        update_status.assert_awaited_once()
        self.assertEqual(update_status.await_args.kwargs["status"], "completed")
        self.assertEqual(update_status.await_args.kwargs["result"]["id"], 88)
        self.assertEqual(update_status.await_args.kwargs["result"]["questions"][0]["stem"], "待审核草稿题干")
        self.assertGreaterEqual(append_event.await_count, 2)
        step_event = append_event.await_args_list[0].kwargs
        self.assertEqual(step_event["event_type"], "step")
        self.assertEqual(step_event["payload"]["step"]["output"]["approved"], 1)
        self.assertEqual(step_event["payload"]["step"]["output"]["rejected"], 1)
        get_task.assert_awaited_once()

        app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
