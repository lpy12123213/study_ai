from __future__ import annotations

# ruff: noqa: E402,I001

# ---- from backend/tests/test_zujuan_parse_questions.py ----
import unittest

from backend.integrations.crawler.zujuan.client import ZujuanCrawler


class TestZujuanParseQuestions(unittest.IsolatedAsyncioTestCase):
    async def test_parse_questions_from_html_parses_items_when_bs4_available(self) -> None:
        crawler = ZujuanCrawler(subject="高中数学")

        html = """
        <div class=" tk-quest-item  quesroot  " questionindex="0" questionid="31391674" bankid="11">
            <div class="exam-item__cnt">
                <p>已知正实数 a,b,c 满足 2^a = log_{0.5}b = c^2，则 a,b,c 的大小关系不可能的是（ ）</p>
            </div>
        </div>
        """

        questions = await crawler._parse_questions_from_html(html, bank_id=11, parse_content=False)

        self.assertGreaterEqual(len(questions), 1)
        self.assertEqual(questions[0].get("question_id"), "31391674")
        self.assertTrue(str(questions[0].get("source_url") or "").endswith("/11q31391674.html"))
        self.assertIn("已知", str(questions[0].get("stem") or ""))

    async def test_parse_questions_from_html_converts_tables_to_latex_array(self) -> None:
        crawler = ZujuanCrawler(subject="高中数学")

        html = """
        <div class=" tk-quest-item  quesroot  " questionindex="0" questionid="31391675" bankid="11">
            <div class="exam-item__cnt">
                <p>已知随机变量的分布列为：</p>
                <table>
                    <tr><th>\\(\\xi\\)</th><th>0</th><th>1</th><th>2</th><th>\\(n\\)</th></tr>
                    <tr><td>\\(P\\)</td><td>\\(p_0\\)</td><td>\\(p_1\\)</td><td>\\(p_2\\)</td><td>\\(p_n\\)</td></tr>
                </table>
            </div>
        </div>
        """

        questions = await crawler._parse_questions_from_html(html, bank_id=11, parse_content=False)

        self.assertEqual(len(questions), 1)
        stem = str(questions[0].get("stem") or "")
        self.assertIn("\\begin{array}", stem)
        self.assertIn("\\xi", stem)
        self.assertIn("p_0", stem)
        self.assertNotIn("\n0\n1\n2", stem)


# ---- from backend/tests/test_zujuan_parsing_patterns.py ----

import unittest

from backend.integrations.crawler.zujuan.parsing import FORMULA_IMG_TAG_PATTERN, IMG_TAG_PATTERN


class TestZujuanParsingPatterns(unittest.TestCase):
    def test_img_tag_pattern_extracts_src(self) -> None:
        html = '<img src="https://example.com/a.png" alt="x" />'
        m = IMG_TAG_PATTERN.search(html)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("src"), "https://example.com/a.png")

    def test_formula_img_tag_pattern_extracts_hash(self) -> None:
        html = (
            '<img src="https://staticzujuan.xkw.com/quesimg/Upload/formula/'
            '37ab7408ffcefcb8e5e1ad4a9c58f1b1.png" style="vertical-align:middle;" />'
        )
        m = FORMULA_IMG_TAG_PATTERN.search(html)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("hash"), "37ab7408ffcefcb8e5e1ad4a9c58f1b1")


# ---- from backend/tests/test_zujuan_quality_score.py ----

import unittest


class TestZujuanQualityScore(unittest.TestCase):
    def setUp(self) -> None:
        from backend.integrations.crawler.zujuan import ZujuanCrawler

        self.crawler = ZujuanCrawler(cookies="", subject="高中数学")

    def test_missing_stem(self) -> None:
        score, flags = self.crawler._quality_score({"stem": ""})
        self.assertEqual(score, 0)
        self.assertIn("missing_stem", flags)

    def test_choice_missing_options(self) -> None:
        q = {
            "type": "单选题",
            "knowledge_points": ["导数"],
            "stem": "已知函数 f(x)=x^2+2x+1，求当 x=1 时 f'(x) 的值。请选择下列选项中正确的一项。",
        }
        score, flags = self.crawler._quality_score(q)
        self.assertIn("choice_missing_options", flags)
        self.assertLess(score, 80)

    def test_choice_with_options(self) -> None:
        q = {
            "type": "单选题",
            "knowledge_points": ["导数"],
            "stem": ("已知函数 f(x)=x^2+2x+1，当 x=1 时 f'(x)=？下列选项中正确的是： A. 1  B. 2  C. 3  D. 4"),
        }
        score, flags = self.crawler._quality_score(q)
        self.assertTrue(any(str(f).startswith("choice_options:") for f in flags))
        self.assertNotIn("choice_missing_options", flags)
        self.assertFalse(any(str(f).startswith("choice_options_incomplete:") for f in flags))
        self.assertGreaterEqual(score, 90)

    def test_kp_match_low(self) -> None:
        q = {
            "type": "填空题",
            "knowledge_points": ["向量的数量积"],
            "stem": "在三角形 ABC 中，已知角 A=30°，角 B=60°，求角 C 的大小，并给出简要说明。",
        }
        score, flags = self.crawler._quality_score(q)
        self.assertIn("kp_match_low", flags)
        self.assertLessEqual(score, 95)

    def test_unbalanced_parentheses(self) -> None:
        q = {
            "type": "填空题",
            "knowledge_points": ["函数"],
            "stem": "已知函数 f(x)=(x+1，求 f(0) 的值。",
        }
        score, flags = self.crawler._quality_score(q)
        self.assertTrue(any(str(f).startswith("unbalanced_") for f in flags))
        self.assertLess(score, 100)


if __name__ == "__main__":
    unittest.main()


# ---- from backend/tests/test_zujuan_client_utils.py ----


import unittest


class TestZujuanClientUtils(unittest.TestCase):
    def test_resolve_url_handles_static_formula_and_relative_paths(self) -> None:
        crawler = ZujuanCrawler(subject="高中数学")

        self.assertEqual(
            crawler._resolve_url("/quesimg/Upload/formula/abc123.png"),
            "https://staticzujuan.xkw.com/quesimg/Upload/formula/abc123.png",
        )
        self.assertEqual(
            crawler._resolve_url("/gzsx/question/list"),
            "https://zujuan.xkw.com/gzsx/question/list",
        )
        self.assertEqual(
            crawler._resolve_url("//staticzujuan.xkw.com/a.svg"),
            "https://staticzujuan.xkw.com/a.svg",
        )

    def test_formula_cache_enforces_lru_limit(self) -> None:
        crawler = ZujuanCrawler(subject="高中数学")
        crawler._formula_cache_max_entries = 2

        crawler._formula_cache_set("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "a")
        crawler._formula_cache_set("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "b")
        self.assertEqual(crawler._formula_cache_get("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "a")

        crawler._formula_cache_set("cccccccccccccccccccccccccccccccc", "c")

        self.assertIsNone(crawler._formula_cache_get("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))
        self.assertEqual(crawler._formula_cache_get("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), "a")
        self.assertEqual(crawler._formula_cache_get("cccccccccccccccccccccccccccccccc"), "c")


if __name__ == "__main__":
    unittest.main()


# ---- from backend/tests/test_zujuan_request_building.py ----


import asyncio
import os
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend.integrations.crawler.zujuan.question_list import fetch_question_list
from backend.integrations.crawler.zujuan.search import search_by_keyword


class TestZujuanAntibotCookieDetection(unittest.TestCase):
    def test_missing_antibot_keys_accepts_alicfw_cookie_pair(self) -> None:
        from backend.integrations.crawler.zujuan.cookies import missing_antibot_keys

        missing = missing_antibot_keys("aliyungf_tc=a; acw_tc=b; alicfw=c; alicfw_gfver=v1.200309.1")

        self.assertEqual(missing, set())


class TestZujuanSubjectRequestDefaults(unittest.TestCase):
    def test_crawler_initializes_static_course_route_from_subject_config(self) -> None:
        from backend.integrations.crawler.zujuan.client import ZujuanCrawler

        crawler = ZujuanCrawler(subject="高中数学")

        self.assertEqual(crawler.course_id_py, "gzsx")

    def test_base_meta_without_course_route_does_not_clear_static_course_route(self) -> None:
        from backend.integrations.crawler.zujuan.client import ZujuanCrawler

        crawler = ZujuanCrawler(subject="高中数学")
        crawler._base_meta_data = [{"QuesBankList": [{"ID": 11, "QuesTypeList": [], "LearnGradeList": []}]}]

        crawler._load_bank_meta_from_base()

        self.assertEqual(crawler.course_id_py, "gzsx")


class FakeResponse:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    def json(self) -> dict:
        return {"code": "0", "data": {"html": "<div questionid=\"123\"></div>"}}


class CapturingClient:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    async def post(self, url: str, *, content: str, headers: dict) -> FakeResponse:
        self.posts.append({"url": url, "content": content, "headers": headers})
        return FakeResponse()


class QuestionListFakeCrawler:
    base_url = "https://zujuan.xkw.com"
    user_agent = "test-agent"
    course_id = 0
    course_id_py = ""

    def __init__(self) -> None:
        self.client = CapturingClient()
        self.cache: dict = {}

    def _use_multi_difficulty_codes(self) -> bool:
        return False

    def _difficulty_code(self, difficulty: str) -> int:
        return 0

    def _question_type_code(self, question_type: str) -> int:
        return 0

    async def _ensure_bank_meta_loaded(self) -> None:
        return None

    def _cache_get(self, key: str):
        return self.cache.get(key)

    def _cache_set(self, key: str, value, ttl: float) -> None:
        self.cache[key] = value

    async def _parse_questions_from_html(self, html: str, bank_id: int, *, parse_content: bool = True) -> list[dict]:
        return [{"question_id": "123", "difficulty": ""}]

    def _requested_difficulty_buckets(self, difficulty: str) -> set[str]:
        return set()


class TestZujuanQuestionListRequest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_question_list_uses_sse_course_route_for_referer_and_origin(self) -> None:
        crawler = QuestionListFakeCrawler()

        await fetch_question_list(
            crawler,
            page_name="zsd",
            bank_id=11,
            category_id="27925",
            course_id_py="gzsx",
            cur_page=1,
            parse_content=False,
        )

        headers = crawler.client.posts[0]["headers"]
        self.assertEqual(headers["Referer"], "https://zujuan.xkw.com/gzsx/zsd27925/")
        self.assertEqual(headers["Origin"], "https://zujuan.xkw.com")
        self.assertIn("application/json", headers["Accept"])


class SearchFakeCrawler:
    client = None
    subject = "高中数学"
    bank_id = 11
    category_id = "27925"
    course_id = 0
    course_id_py = ""

    def __init__(self) -> None:
        self.fetch_calls: list[dict] = []

    def _apply_search_constraints(
        self,
        *,
        subject: str,
        edu_level: str,
        difficulty: str,
        require_difficulty: bool,
        strict_subject: bool,
    ) -> tuple[str, str]:
        return "高中数学", ""

    async def _ai_search(self, keyword: str) -> dict:
        return {"success": True, "payload": {"url": "/gzsx/zsd27925/o2", "data": {"params": {"bank_id": 11}}}}

    def _parse_target_from_payload(self, payload: dict) -> dict:
        return {
            "page_name": "zsd",
            "category_id": "27925",
            "bank_id": 11,
            "course_id_py": "gzsx",
        }

    def _resolve_textbook_category_id(self, textbook_version: str) -> str:
        return ""

    def _resolve_learn_grade_id(self, learn_grade: str, learn_grade_id: int = 0) -> int:
        return 0

    async def _fetch_question_list(self, **kwargs):
        self.fetch_calls.append(kwargs)
        return ([{"question_id": "123", "stem": "这是一道用于测试请求链路的数据题干。", "difficulty": ""}], {"raw_count": 1})

    def _matches_local_filters(self, question: dict, **kwargs) -> bool:
        return True

    def _quality_score(self, question: dict) -> tuple[int, list[str]]:
        return 100, []

    def _normalize_elective_mode(self, elective_mode: str, exclude_elective: bool) -> str:
        return "include"


class TestZujuanSearchRequestFlow(unittest.IsolatedAsyncioTestCase):
    async def test_search_forwards_sse_course_route_to_question_list(self) -> None:
        crawler = SearchFakeCrawler()

        result = await search_by_keyword(crawler, keyword="函数", limit=1, max_pages=1, parse_content=False)

        self.assertTrue(result["success"])
        self.assertEqual(crawler.fetch_calls[0]["course_id_py"], "gzsx")


class ChunkedPagingFakeCrawler(SearchFakeCrawler):
    """带门控的 _fetch_question_list，用于观测分页的并发与早停行为。"""

    def __init__(self, *, empty_pages: set[int] = frozenset(), failing_pages: set[int] = frozenset()) -> None:
        super().__init__()
        self.events: list[tuple[str, int]] = []
        self.empty_pages = set(empty_pages)
        self.failing_pages = set(failing_pages)

    async def _fetch_question_list(self, **kwargs):  # type: ignore[no-untyped-def]
        page = int(kwargs.get("cur_page", 0) or 0)
        self.events.append(("start", page))
        await asyncio.sleep(0.02)
        self.events.append(("end", page))
        if page in self.failing_pages:
            raise httpx.ConnectError("simulated transient network failure")
        if page in self.empty_pages:
            return [], {"raw_count": 0, "page": page}
        return (
            [
                {
                    "question_id": f"q{page}",
                    "stem": "这是一道用于测试分页并发行为的完整题干。",
                    "difficulty": "",
                }
            ],
            {"raw_count": 1, "page": page},
        )


class TestZujuanSearchChunkedPaging(unittest.IsolatedAsyncioTestCase):
    async def test_search_fetches_pages_within_chunk_concurrently(self) -> None:
        crawler = ChunkedPagingFakeCrawler()

        with patch.dict(os.environ, {"ZUJUAN_SEARCH_PAGE_CONCURRENCY": "3"}):
            result = await search_by_keyword(crawler, keyword="函数", limit=10, max_pages=3, parse_content=False)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["questions"]), 3)
        starts = [page for kind, page in crawler.events if kind == "start"]
        # 块内 3 页应同时进入请求（所有 start 先于任何 end）。
        self.assertEqual(starts, [1, 2, 3])
        self.assertTrue(all(kind == "start" for kind, _ in crawler.events[:3]))

    async def test_search_stops_paging_between_chunks_when_limit_reached(self) -> None:
        crawler = ChunkedPagingFakeCrawler()

        with patch.dict(os.environ, {"ZUJUAN_SEARCH_PAGE_CONCURRENCY": "2"}):
            result = await search_by_keyword(crawler, keyword="函数", limit=1, max_pages=5, parse_content=False)

        self.assertTrue(result["success"])
        fetched_pages = {page for kind, page in crawler.events if kind == "start"}
        # 第一块取 1-2 页后凑够 limit，不再请求第 3 页及以后。
        self.assertEqual(fetched_pages, {1, 2})
        self.assertEqual(len(result["questions"]), 1)

    async def test_search_stops_processing_remaining_chunk_pages_on_empty_page(self) -> None:
        crawler = ChunkedPagingFakeCrawler(empty_pages={1})

        with patch.dict(os.environ, {"ZUJUAN_SEARCH_PAGE_CONCURRENCY": "2"}):
            result = await search_by_keyword(crawler, keyword="函数", limit=10, max_pages=4, parse_content=False)

        # 第 1 页为空：即使同块的第 2 页已被取回，也不并入结果（与旧的串行行为一致）。
        self.assertTrue(result["success"])
        self.assertEqual(result["questions"], [])

    async def test_search_continues_when_single_page_raises_network_error(self) -> None:
        crawler = ChunkedPagingFakeCrawler(failing_pages={2})

        with patch.dict(os.environ, {"ZUJUAN_SEARCH_PAGE_CONCURRENCY": "2"}):
            result = await search_by_keyword(crawler, keyword="函数", limit=10, max_pages=4, parse_content=False)

        # 第 2 页抛网络异常：第 1/3/4 页正常并入，分页不因瞬时错误早停。
        self.assertTrue(result["success"])
        self.assertEqual([q["question_id"] for q in result["questions"]], ["q1", "q3", "q4"])
        fetched_pages = {page for kind, page in crawler.events if kind == "start"}
        self.assertEqual(fetched_pages, {1, 2, 3, 4})
        failed_pages = [
            dbg
            for dbg in result.get("trace", {}).get("pages", [])
            if str(dbg.get("error") or "").startswith("fetch_failed")
        ]
        self.assertEqual(len(failed_pages), 1)
        self.assertTrue(failed_pages[0].get("retryable"))


class TestZujuanBatchDetailsDefaults(unittest.IsolatedAsyncioTestCase):
    async def test_batch_get_question_details_has_no_default_inter_batch_delay(self) -> None:
        crawler = ZujuanCrawler(subject="高中数学")

        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(
                crawler,
                "get_question_detail",
                new=AsyncMock(return_value={"success": True, "question_id": "q"}),
            ),
        ):
            os.environ.pop("ZUJUAN_BATCH_GET_DETAILS_DELAY_S", None)
            started = time.monotonic()
            result = await crawler.batch_get_question_details(["1", "2", "3"], max_concurrent=1)
            elapsed = time.monotonic() - started

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 3)
        # 旧默认批间延迟 0.2s * 2 批 = 0.4s；新默认无延迟，留足裕量断言 < 0.3s。
        self.assertLess(elapsed, 0.3)


class TestZujuanCrawlerInitialization(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_defaults_to_visitor_mode_without_cookie_bootstrap(self) -> None:
        from backend.integrations.crawler.zujuan.client import ZujuanCrawler

        class FakeRobots:
            async def crawl_delay(self, url: str, *, user_agent: str = ""):
                return None

            async def assert_allowed(self, url: str, *, user_agent: str = "") -> None:
                return None

        with (
            patch("backend.integrations.crawler.zujuan.client.load_env_login", return_value={"cookies": "userId=123", "is_logged_in": True}),
            patch("backend.integrations.crawler.zujuan.client.load_antibot_cookie_cache", return_value="aliyungf_tc=a; acw_tc=b"),
            patch("backend.integrations.crawler.zujuan.client.get_cookies_with_playwright", new_callable=AsyncMock) as get_cookies,
            patch.dict(
                "os.environ",
                {
                    "ZUJUAN_COOKIE_FILE": "",
                    "ZUJUAN_USE_ENV_COOKIES_FOR_SEARCH": "0",
                    "ZUJUAN_USE_CACHED_ANTIBOT_COOKIES": "0",
                    "ZUJUAN_AUTO_BOOTSTRAP_COOKIES": "0",
                },
                clear=False,
            ),
        ):
            crawler = ZujuanCrawler(subject="高中数学")
            crawler._robots = FakeRobots()
            await crawler.initialize()
            try:
                self.assertEqual(crawler.cookies, "")
                self.assertNotIn("Cookie", crawler.client.headers)
                get_cookies.assert_not_awaited()
            finally:
                await crawler.close()


if __name__ == "__main__":
    unittest.main()


# ---- from backend/tests/test_zujuan_export_behavior.py ----

import json
import unittest
from types import SimpleNamespace


class TestZujuanExportBehavior(unittest.IsolatedAsyncioTestCase):
    def test_diagnose_export_resolves_repo_root_env_file(self) -> None:
        import backend.integrations.mcp.core.diagnostics as diagnostics

        with patch.object(diagnostics, "__file__", r"C:\repo\backend\mcp\core\diagnostics.py"):
            resolved = diagnostics.resolve_repo_env_file()

        self.assertEqual(str(resolved), r"C:\repo\.env")

    async def test_fetch_formula_svg_uses_crawler_http_client(self) -> None:
        from backend.integrations.crawler.zujuan.formulas import fetch_formula_svg

        class FakeSvgResponse:
            text = "<svg></svg>"

        class FakeSvgClient:
            def __init__(self) -> None:
                self.gets: list[dict] = []

            async def get(self, url: str, *, headers: dict, timeout: float) -> FakeSvgResponse:
                self.gets.append({"url": url, "headers": headers, "timeout": timeout})
                return FakeSvgResponse()

        client = FakeSvgClient()
        crawler = SimpleNamespace(user_agent="UA", client=client)

        svg = await fetch_formula_svg(crawler, "https://staticzujuan.xkw.com/quesimg/Upload/formula/abc.png")

        self.assertEqual(svg, "<svg></svg>")
        self.assertEqual(client.gets[0]["url"], "https://staticzujuan.xkw.com/quesimg/Upload/formula/abc.svg")
        self.assertEqual(client.gets[0]["headers"]["User-Agent"], "UA")
        self.assertEqual(client.gets[0]["headers"]["Referer"], "https://zujuan.xkw.com/")
        self.assertEqual(client.gets[0]["timeout"], 10.0)

    async def test_export_to_basket_uses_subject_question_type_id_map(self) -> None:
        from backend.integrations.crawler.zujuan.basket import export_to_basket

        captured: dict = {}

        class FakeResponse:
            status_code = 200
            text = json.dumps({"questions": [{"questionId": 1}]}, ensure_ascii=False)

            def json(self):  # type: ignore[no-untyped-def]
                return json.loads(self.text)

        class FakeClient:
            def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                _ = args, kwargs

            async def __aenter__(self):  # type: ignore[no-untyped-def]
                return self

            async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
                _ = exc_type, exc, tb
                return False

            async def post(self, url, data=None, headers=None):  # type: ignore[no-untyped-def]
                captured["url"] = url
                captured["data"] = data
                captured["headers"] = headers
                return FakeResponse()

        crawler = SimpleNamespace(
            bank_id=15,
            subject="高中生物",
            base_url="https://zujuan.xkw.com",
            user_agent="UA",
            ques_type_map={"解答题": 3106},
            get_available_filters=AsyncMock(
                return_value={
                    "success": True,
                    "question_types": [{"id": 3106, "name": "解答题"}],
                }
            ),
            _question_type_code=lambda question_type: 3106 if question_type == "解答题" else 0,
        )

        with patch(
            "backend.integrations.crawler.zujuan.basket.get_login_session_with_playwright",
            new=AsyncMock(
                return_value={
                    "is_logged_in": True,
                    "cookies": "userId=123; bankId=15",
                    "csrf_token": "csrf-token",
                }
            ),
        ), patch("backend.integrations.crawler.zujuan.basket.httpx.AsyncClient", FakeClient):
            result = await export_to_basket(
                crawler,
                question_ids=["1"],
                question_details=[{"question_id": "1", "type": "解答题", "difficulty": "中等"}],
                auto_login=False,
            )

        self.assertTrue(result["success"])
        basket_items = json.loads(captured["data"]["basketJson"])
        self.assertEqual(basket_items[0]["quesTypeId"], 3106)

    async def test_export_to_basket_marks_dynamic_select_types(self) -> None:
        from backend.integrations.crawler.zujuan.basket import export_to_basket

        captured: dict = {}

        class FakeResponse:
            status_code = 200
            text = json.dumps({"questions": [{"questionId": 1}]}, ensure_ascii=False)

            def json(self):  # type: ignore[no-untyped-def]
                return json.loads(self.text)

        class FakeClient:
            def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                _ = args, kwargs

            async def __aenter__(self):  # type: ignore[no-untyped-def]
                return self

            async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
                _ = exc_type, exc, tb
                return False

            async def post(self, url, data=None, headers=None):  # type: ignore[no-untyped-def]
                captured["url"] = url
                captured["data"] = data
                captured["headers"] = headers
                return FakeResponse()

        crawler = SimpleNamespace(
            bank_id=15,
            subject="高中生物",
            base_url="https://zujuan.xkw.com",
            user_agent="UA",
            ques_type_map={"单选题": 3101},
            get_available_filters=AsyncMock(
                return_value={
                    "success": True,
                    "question_types": [{"id": 3101, "name": "单选题"}],
                }
            ),
        )

        with patch(
            "backend.integrations.crawler.zujuan.basket.get_login_session_with_playwright",
            new=AsyncMock(
                return_value={
                    "is_logged_in": True,
                    "cookies": "userId=123; bankId=15",
                    "csrf_token": "csrf-token",
                }
            ),
        ), patch("backend.integrations.crawler.zujuan.basket.httpx.AsyncClient", FakeClient):
            result = await export_to_basket(
                crawler,
                question_ids=["1"],
                question_details=[{"question_id": "1", "type": "单选题-1个小题", "difficulty": "中等"}],
                auto_login=False,
            )

        self.assertTrue(result["success"])
        basket_items = json.loads(captured["data"]["basketJson"])
        self.assertEqual(basket_items[0]["quesTypeId"], 3101)
        self.assertTrue(basket_items[0]["ext"]["isSelectType"])

    async def test_resolve_question_type_ids_prefers_current_subject_filters(self) -> None:
        from backend.integrations.crawler.zujuan.basket import _resolve_question_type_ids

        crawler = SimpleNamespace(
            ques_type_map={"解答题": 5104, "单选题": 1200401},
            get_available_filters=AsyncMock(
                return_value={
                    "success": True,
                    "question_types": [
                        {"id": 3101, "name": "单选题"},
                        {"id": 3103, "name": "多选题"},
                        {"id": 3106, "name": "解答题"},
                    ],
                }
            ),
        )

        resolved = await _resolve_question_type_ids(crawler)

        self.assertEqual(resolved["解答题"], 3106)
        self.assertEqual(resolved["单选题"], 3101)

    def test_resolve_export_question_type_id_normalizes_composite_type_names(self) -> None:
        from backend.integrations.crawler.zujuan.basket import _resolve_export_question_type_id

        type_map = {
            "单选题": 3101,
            "多选题": 3103,
            "解答题": 3106,
            "实验题": 3107,
        }

        self.assertEqual(_resolve_export_question_type_id("单选题-1个小题", type_map), 3101)
        self.assertEqual(_resolve_export_question_type_id("多选题-3个答案", type_map), 3103)
        self.assertEqual(_resolve_export_question_type_id("解答题", type_map), 3106)

    def test_is_select_question_type_supports_dynamic_subject_ids(self) -> None:
        from backend.integrations.crawler.zujuan.basket import _is_select_question_type

        type_map = {
            "单选题": 3101,
            "多选题": 3103,
            "解答题": 3106,
        }

        self.assertTrue(_is_select_question_type("单选题-1个小题", 3101, type_map))
        self.assertTrue(_is_select_question_type("多选题", 3103, type_map))
        self.assertFalse(_is_select_question_type("解答题", 3106, type_map))


if __name__ == "__main__":
    unittest.main()
