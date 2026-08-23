import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
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

    async def test_crawl_task_upserts_questions_in_batches(self) -> None:
        from backend.generation.question_library import runner as ql_runner

        questions = [
            {
                "question_id": f"q-{i}",
                "stem": f"这是第 {i} 道用于验证批量入库的完整题干，长度足以通过过滤。",
                "answer": "",
                "analysis": "",
                "difficulty": "",
                "question_type": "",
                "source": "",
                "date": "",
            }
            for i in range(1, 61)
        ]

        class SuccessCrawler:
            async def search_by_keyword(self, **kwargs: Any) -> dict:
                return {"success": True, "questions": [dict(q) for q in questions], "count": len(questions)}

        fake_runtime = _InlineTaskRuntime()
        with (
            patch.object(ql_runner, "task_runtime", fake_runtime),
            patch.object(ql_runner, "get_crawler", new=AsyncMock(return_value=SuccessCrawler())),
            patch.object(ql_runner, "upsert_question_cache", new=AsyncMock(return_value=None)) as cache_mock,
            patch.object(ql_runner, "upsert_question_library_items", new=AsyncMock(return_value=None)) as library_mock,
        ):
            task = await ql_runner.create_crawl_task(
                user_id="u-1",
                request={"task_id": "ql-crawl-batch", "subject": "高中数学", "query": "函数", "limit": 60},
            )

        self.assertEqual(task.status, "completed")
        # 60 题按 25 一块批量写库：3 次、每次载荷不超过 25。
        self.assertEqual(cache_mock.await_count, 3)
        batch_sizes = [len(call.args[0]) for call in cache_mock.await_args_list]
        self.assertEqual(batch_sizes, [25, 25, 10])
        self.assertEqual(library_mock.await_count, 3)
        item_saved = [event for event in fake_runtime.events if event.get("type") == "item_saved"]
        self.assertEqual(len(item_saved), 60)
        done_events = [event for event in fake_runtime.events if event.get("type") == "done"]
        self.assertEqual(done_events[-1]["data"]["inserted"], 60)

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


    async def test_crawl_task_runs_multi_query_plan_with_cross_query_dedup(self) -> None:
        from backend.generation.question_library import runner as ql_runner

        class MultiQueryCrawler:
            def __init__(self) -> None:
                self.keywords: list[str] = []

            async def search_by_keyword(self, **kwargs: Any) -> dict:
                keyword = str(kwargs.get("keyword") or "")
                self.keywords.append(keyword)
                # 两个查询都返回重叠的 q-shared + 各自独占题，验证跨查询去重。
                questions = [
                    {
                        "question_id": "q-shared",
                        "stem": "两个查询都会返回的共享题干，应只入库一次。",
                        "answer": "",
                        "analysis": "",
                        "difficulty": "",
                        "question_type": "",
                        "source": "",
                        "date": "",
                    },
                    {
                        "question_id": f"q-{keyword}",
                        "stem": f"关键词 {keyword} 的独占题干。",
                        "answer": "",
                        "analysis": "",
                        "difficulty": "",
                        "question_type": "",
                        "source": "",
                        "date": "",
                    },
                ]
                return {"success": True, "questions": questions, "count": len(questions)}

        crawler = MultiQueryCrawler()
        fake_runtime = _InlineTaskRuntime()
        with (
            patch.object(ql_runner, "task_runtime", fake_runtime),
            patch.object(ql_runner, "get_crawler", new=AsyncMock(return_value=crawler)),
            patch.object(ql_runner, "upsert_question_cache", new=AsyncMock(return_value=None)) as cache_mock,
            patch.object(ql_runner, "upsert_question_library_items", new=AsyncMock(return_value=None)),
        ):
            task = await ql_runner.create_crawl_task(
                user_id="u-1",
                request={
                    "task_id": "ql-crawl-multi",
                    "subject": "高中物理",
                    "queries": ["牛顿运动定律", "电磁感应"],
                    "limit": 30,
                },
            )

        self.assertEqual(task.status, "completed")
        self.assertEqual(crawler.keywords, ["牛顿运动定律", "电磁感应"])
        # 去重后 3 题（q-shared 只算一次）。
        all_saved = [item["question_id"] for call in cache_mock.await_args_list for item in call.args[0]]
        self.assertEqual(sorted(all_saved), ["q-shared", "q-牛顿运动定律", "q-电磁感应"])
        done_events = [event for event in fake_runtime.events if event.get("type") == "done"]
        self.assertEqual(done_events[-1]["data"]["inserted"], 3)

    async def test_crawl_task_fails_only_when_every_query_fails(self) -> None:
        from backend.generation.question_library import runner as ql_runner

        class FlakyCrawler:
            def __init__(self) -> None:
                self.calls = 0

            async def search_by_keyword(self, **kwargs: Any) -> dict:
                self.calls += 1
                if self.calls == 1:
                    return {
                        "success": False,
                        "error": "js_challenge",
                        "instructions": ["设置 ZUJUAN_COOKIE_FILE 后重试。"],
                        "trace": {"pages": [{"error": "js_challenge", "status": 200}]},
                    }
                return {
                    "success": True,
                    "questions": [
                        {
                            "question_id": "q-ok",
                            "stem": "第二个查询成功的完整题干。",
                            "answer": "",
                            "analysis": "",
                            "difficulty": "",
                            "question_type": "",
                            "source": "",
                            "date": "",
                        }
                    ],
                    "count": 1,
                }

        fake_runtime = _InlineTaskRuntime()
        with (
            patch.object(ql_runner, "task_runtime", fake_runtime),
            patch.object(ql_runner, "get_crawler", new=AsyncMock(return_value=FlakyCrawler())),
            patch.object(ql_runner, "upsert_question_cache", new=AsyncMock(return_value=None)),
            patch.object(ql_runner, "upsert_question_library_items", new=AsyncMock(return_value=None)),
        ):
            task = await ql_runner.create_crawl_task(
                user_id="u-1",
                request={
                    "task_id": "ql-crawl-partial",
                    "subject": "高中物理",
                    "queries": ["坏查询", "好查询"],
                    "limit": 10,
                },
            )

        # 第一个查询失败不终止批量：第二个查询入库，任务整体成功。
        self.assertEqual(task.status, "completed")
        done_events = [event for event in fake_runtime.events if event.get("type") == "done"]
        self.assertEqual(done_events[-1]["data"]["inserted"], 1)

    async def test_crawl_task_accepts_domain_plan(self) -> None:
        from backend.generation.question_library import runner as ql_runner

        class CountingCrawler:
            def __init__(self) -> None:
                self.keywords: list[str] = []

            async def search_by_keyword(self, **kwargs: Any) -> dict:
                self.keywords.append(str(kwargs.get("keyword") or ""))
                return {"success": True, "questions": [], "count": 0}

        crawler = CountingCrawler()
        fake_runtime = _InlineTaskRuntime()
        with (
            patch.object(ql_runner, "task_runtime", fake_runtime),
            patch.object(ql_runner, "get_crawler", new=AsyncMock(return_value=crawler)),
            patch.object(ql_runner, "upsert_question_cache", new=AsyncMock(return_value=None)),
            patch.object(ql_runner, "upsert_question_library_items", new=AsyncMock(return_value=None)),
        ):
            task = await ql_runner.create_crawl_task(
                user_id="u-1",
                request={
                    "task_id": "ql-crawl-domains",
                    "subject": "高中物理",
                    "domains": ["mechanics"],
                    "limit": 5,
                },
            )

        self.assertEqual(task.status, "completed")
        # mechanics 域展开为力学默认关键词表（20 个）。
        self.assertEqual(len(crawler.keywords), 20)
        self.assertIn("牛顿运动定律", crawler.keywords)


class TestCrawlImportRunImport(unittest.IsolatedAsyncioTestCase):
    async def test_run_import_continues_when_single_query_raises(self) -> None:
        from backend.cli import question_library_crawl as qlc
        from backend.cli.question_library_crawl import CrawlImportConfig

        async def fake_crawl_query(
            crawler: Any, config: Any, *, plan_item: Any, seen_ids: set[str]
        ) -> list[dict]:
            if plan_item.query == "bad-query":
                raise RuntimeError("simulated network failure")
            seen_ids.add("q-ok-1")
            return [
                {
                    "question_id": "q-ok-1",
                    "stem": "用于验证单查询异常不终止导入的完整题干。",
                    "answer": "",
                    "analysis": "",
                    "difficulty": "",
                    "question_type": "",
                    "source": "",
                    "date": "",
                }
            ]

        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "crawl.jsonl"
            config = CrawlImportConfig(
                subject="高中物理",
                target=5,
                custom_keywords=("good-query", "bad-query"),
                rounds=1,
                concurrency=2,
                log_path=log_path,
                summary_path=Path(tmp) / "summary.json",
            )
            crawler = AsyncMock()
            with (
                # patch.dict 回滚 run_import 里 os.environ.setdefault 的副作用
                patch.dict(os.environ, {}, clear=False),
                patch.object(qlc, "load_existing_question_ids", new=AsyncMock(return_value=set())),
                patch.object(qlc, "ZujuanCrawler", return_value=crawler),
                patch.object(qlc, "_crawl_query", new=fake_crawl_query),
                patch.object(qlc, "upsert_question_cache", new=AsyncMock(return_value=None)) as cache_mock,
                patch.object(qlc, "upsert_question_library_items", new=AsyncMock(return_value=None)),
            ):
                summary = await qlc.run_import(config)

            # 坏查询只记 query_failed：好查询的结果正常入库，爬虫正常关闭，汇总可读。
            self.assertEqual(summary["inserted"], 1)
            self.assertFalse(summary["success"])
            cache_mock.assert_awaited_once()
            crawler.close.assert_awaited_once()
            events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            failures = [e for e in events if e.get("message") == "query_failed" and e.get("query") == "bad-query"]
            self.assertEqual(len(failures), 1)
            self.assertIn("RuntimeError", str(failures[0].get("error")))
