import unittest
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.shared.tasks.runtime import RuntimeTask


class _InlineTaskRuntime:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.failed: Optional[dict] = None

    async def create_task(self, **kwargs: Any) -> RuntimeTask:
        task = RuntimeTask(
            task_id=kwargs["task_id"],
            user_id=kwargs["user_id"],
            task_type=kwargs["task_type"],
            title=kwargs["title"],
            request=kwargs["request"],
            parent_task_id=kwargs.get("parent_task_id"),
        )
        await kwargs["runner_factory"](task)
        return task

    async def append_event(self, task: RuntimeTask, event: dict) -> None:
        self.events.append(event)

    async def complete_task(self, task: RuntimeTask, *, result: Optional[dict] = None) -> None:
        task.status = "completed"

    async def fail_task(
        self,
        task: RuntimeTask,
        message: str,
        *,
        error: Optional[dict] = None,
        emit_event: bool = True,
    ) -> None:
        task.status = "failed"
        task.error = message
        self.failed = {"message": message, "error": error, "emit_event": emit_event}
        if emit_event:
            await self.append_event(task, {"type": "error", "data": {"error": message}})


class _ChallengeCrawler:
    async def search_by_keyword(self, **_kwargs: Any) -> dict:
        return {
            "success": False,
            "error": "js_challenge",
            "instructions": [
                "题库请求返回了 JavaScript 挑战页，不能作为试题数据解析。",
                "设置 ZUJUAN_COOKIE_FILE 后重启服务再试。",
            ],
            "trace": {"pages": [{"error": "js_challenge", "status": 200}]},
            "login_required": False,
            "cookie_expired": False,
        }


class TestQuestionLibraryCrawl(unittest.IsolatedAsyncioTestCase):
    def test_crawl_endpoint_exists(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.post("/api/question-library/crawl", json={"subject": "高中数学", "query": "函数"})
        # NOTE: the app has a GET/HEAD SPA fallback route; unknown POST paths return 405.
        self.assertNotIn(resp.status_code, {404, 405})

    def test_gaokao_crawl_endpoints_exist(self) -> None:
        app = create_app()
        client = TestClient(app)
        stream_resp = client.post("/api/question-library/gaokao/crawl", json={})
        task_resp = client.post("/api/tasks/question-library/gaokao-crawl", json={})
        self.assertNotIn(stream_resp.status_code, {404, 405})
        self.assertNotIn(task_resp.status_code, {404, 405})

    def test_task_stream_endpoint_exists(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/question-library/tasks/test-task/stream")
        self.assertNotEqual(resp.status_code, 404)

    async def test_gaokao_crawl_only_persists_source_matched_questions(self) -> None:
        from backend.generation.question_library import runner as ql_runner

        class GaokaoCrawler:
            def __init__(self) -> None:
                self.kwargs: dict = {}

            async def search_by_keyword(self, **kwargs: Any) -> dict:
                self.kwargs = dict(kwargs)
                return {
                    "success": True,
                    "questions": [
                        {
                            "question_id": "gk-match",
                            "stem": "匹配声明试卷的真题题干。",
                            "answer": "A",
                            "analysis": "解析",
                            "source": "2024年普通高等学校招生全国统一考试·新课标I卷",
                            "date": "2024/06",
                            "question_index": 1,
                            "links": {"source_paper_url": "https://source.test/paper"},
                        },
                        {
                            "question_id": "gk-wrong-paper",
                            "stem": "同年但属于另一套试卷。",
                            "source": "2024年普通高等学校招生全国统一考试·全国甲卷",
                            "date": "2024/06",
                        },
                        {
                            "question_id": "gk-no-source",
                            "stem": "没有出处的题目。",
                            "source": "",
                            "date": "2024/06",
                        },
                    ],
                }

        crawler = GaokaoCrawler()
        fake_runtime = _InlineTaskRuntime()
        with (
            patch.object(ql_runner, "task_runtime", fake_runtime),
            patch.object(ql_runner, "get_crawler", new=AsyncMock(return_value=crawler)),
            patch.object(
                ql_runner,
                "upsert_gaokao_questions",
                new=AsyncMock(return_value={"upserted": 1, "question_ids": ["gk-match"]}),
            ) as upsert_mock,
        ):
            task = await ql_runner.create_gaokao_crawl_task(
                user_id="u-1",
                request={
                    "task_id": "gaokao-crawl-1",
                    "subject": "高中数学",
                    "query": "新课标I卷",
                    "exam_year": 2024,
                    "region": "全国",
                    "paper_name": "2024年新课标I卷数学",
                    "paper_variant": "新课标I卷",
                    "source_contains": "新课标I卷",
                    "source_url": "https://official.test/2024-math.pdf",
                    "verified": True,
                },
            )

        self.assertEqual(task.status, "completed")
        self.assertEqual(crawler.kwargs["year"], 2024)
        self.assertEqual(crawler.kwargs["source_contains"], "新课标I卷")
        upsert_mock.assert_awaited_once()
        saved = upsert_mock.await_args.kwargs["items"]
        self.assertEqual([item["question_id"] for item in saved], ["gk-match"])
        self.assertEqual(saved[0]["source"]["question_number"], "1")
        self.assertEqual(saved[0]["source"]["source_url"], "https://official.test/2024-math.pdf")
        self.assertTrue(saved[0]["source"]["verified"])
        done = [event for event in fake_runtime.events if event.get("type") == "done"][-1]["data"]
        self.assertEqual(done["inserted"], 1)
        self.assertEqual(done["skipped_missing_source"], 1)
        self.assertEqual(done["skipped_source_mismatch"], 1)

    async def test_gaokao_crawl_fails_when_no_source_matches(self) -> None:
        from backend.generation.question_library import runner as ql_runner

        class WrongSourceCrawler:
            async def search_by_keyword(self, **_kwargs: Any) -> dict:
                return {
                    "success": True,
                    "questions": [
                        {
                            "question_id": "wrong-1",
                            "stem": "另一试卷题目",
                            "source": "2024年全国甲卷",
                            "date": "2024/06",
                        }
                    ],
                }

        fake_runtime = _InlineTaskRuntime()
        with (
            patch.object(ql_runner, "task_runtime", fake_runtime),
            patch.object(ql_runner, "get_crawler", new=AsyncMock(return_value=WrongSourceCrawler())),
            patch.object(ql_runner, "upsert_gaokao_questions", new=AsyncMock()) as upsert_mock,
        ):
            task = await ql_runner.create_gaokao_crawl_task(
                user_id="u-1",
                request={
                    "task_id": "gaokao-crawl-no-match",
                    "subject": "高中数学",
                    "query": "新课标I卷",
                    "exam_year": 2024,
                    "region": "全国",
                    "paper_name": "2024年新课标I卷数学",
                    "source_contains": "新课标I卷",
                },
            )

        self.assertEqual(task.status, "failed")
        self.assertEqual(fake_runtime.failed["error"]["error"], "gaokao_source_not_matched")
        upsert_mock.assert_not_awaited()

    async def test_crawl_task_failure_preserves_challenge_recovery_guidance(self) -> None:
        from backend.generation.question_library import runner as ql_runner

        fake_runtime = _InlineTaskRuntime()
        with (
            patch.object(ql_runner, "task_runtime", fake_runtime),
            patch.object(ql_runner, "get_crawler", new=AsyncMock(return_value=_ChallengeCrawler())),
        ):
            task = await ql_runner.create_crawl_task(
                user_id="u-1",
                request={"task_id": "ql-crawl-test", "subject": "高中数学", "query": "函数", "limit": 1},
            )

        self.assertEqual(task.status, "failed")
        self.assertIsNotNone(fake_runtime.failed)
        error_payload = fake_runtime.failed["error"]
        self.assertEqual(error_payload["error"], "js_challenge")
        self.assertFalse(error_payload["login_required"])
        self.assertIn("ZUJUAN_COOKIE_FILE", " ".join(error_payload["instructions"]))
        self.assertEqual(error_payload["trace"]["pages"][0]["error"], "js_challenge")
        error_events = [event for event in fake_runtime.events if event.get("type") == "error"]
        self.assertEqual(error_events[-1]["data"]["error"], "js_challenge")
        self.assertIn("ZUJUAN_COOKIE_FILE", " ".join(error_events[-1]["data"]["instructions"]))

    async def test_crawl_task_failure_preserves_cookie_file_configuration_error(self) -> None:
        from backend.generation.question_library import runner as ql_runner
        from backend.integrations.crawler.zujuan.cookies import ZujuanCookieFileError

        fake_runtime = _InlineTaskRuntime()
        config_error = ZujuanCookieFileError(
            error="zujuan_cookie_file_missing",
            message="ZUJUAN_COOKIE_FILE points to a missing cookie file: C:/missing/cookies.txt",
            path="C:/missing/cookies.txt",
            instructions=[
                "请检查 ZUJUAN_COOKIE_FILE 指向的 Netscape/curl 访客 Cookie 文件是否存在。",
                "相对路径会从 study_ai 仓库根目录解析；更新配置后重启后端服务再试。",
            ],
        )
        with (
            patch.object(ql_runner, "task_runtime", fake_runtime),
            patch.object(ql_runner, "get_crawler", new=AsyncMock(side_effect=config_error)),
        ):
            task = await ql_runner.create_crawl_task(
                user_id="u-1",
                request={"task_id": "ql-crawl-cookie-error", "subject": "高中数学", "query": "函数", "limit": 1},
            )

        self.assertEqual(task.status, "failed")
        error_payload = fake_runtime.failed["error"]
        self.assertEqual(error_payload["error"], "zujuan_cookie_file_missing")
        self.assertEqual(error_payload["cookie_file"]["variable"], "ZUJUAN_COOKIE_FILE")
        self.assertIn("missing", error_payload["message"])
        self.assertIn("仓库根目录", " ".join(error_payload["instructions"]))
