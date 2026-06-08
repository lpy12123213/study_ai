from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

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


class TestZujuanSubjectSearchIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_subject_overrides_do_not_pollute_active_search(self) -> None:
        from backend.integrations.crawler.zujuan.client import ZujuanCrawler

        crawler = ZujuanCrawler(subject="高中数学")
        first_entered = asyncio.Event()
        observations: list[tuple[str, str]] = []

        async def fake_search_impl(**kwargs):  # type: ignore[no-untyped-def]
            inst = kwargs["self"]
            subject = str(kwargs.get("subject") or "")
            resolved, _difficulty = inst._apply_search_constraints(
                subject=subject,
                edu_level=str(kwargs.get("edu_level") or ""),
                difficulty=str(kwargs.get("difficulty") or ""),
                require_difficulty=bool(kwargs.get("require_difficulty")),
                strict_subject=bool(kwargs.get("strict_subject", True)),
            )
            if subject == "高中物理":
                first_entered.set()
                await asyncio.sleep(0.05)
            else:
                await first_entered.wait()
            observations.append((resolved, inst.subject))
            return {"success": True, "questions": []}

        with patch("backend.integrations.crawler.zujuan.search.search_by_keyword", new=fake_search_impl):
            first = asyncio.create_task(crawler.search_by_keyword("函数", subject="高中物理", limit=1))
            await first_entered.wait()
            second = asyncio.create_task(crawler.search_by_keyword("化学平衡", subject="高中化学", limit=1))
            await asyncio.gather(first, second)

        self.assertIn(("高中物理", "高中物理"), observations)
        self.assertIn(("高中化学", "高中化学"), observations)


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


class DetailFakeResponse:
    status_code = 200

    def __init__(self, text: str) -> None:
        self.text = text


class DetailCapturingClient:
    def __init__(self, html: str) -> None:
        self.html = html
        self.gets: list[dict] = []

    async def get(
        self,
        url: str,
        *,
        headers: dict | None = None,
        timeout: float | None = None,
        follow_redirects: bool | None = None,
    ) -> DetailFakeResponse:
        self.gets.append(
            {
                "url": url,
                "headers": headers or {},
                "timeout": timeout,
                "follow_redirects": follow_redirects,
            }
        )
        return DetailFakeResponse(self.html)


class DetailFakeCrawler:
    base_url = "https://zujuan.xkw.com"
    user_agent = "test-agent"

    def __init__(self, html: str) -> None:
        self.client = DetailCapturingClient(html)

    def _question_url(self, question_id: str) -> str:
        return f"{self.base_url}/15q{question_id}.html"

    async def _replace_formulas_with_latex(self, html: str) -> str:
        return html

    async def _replace_formulas_with_svg(self, html: str) -> str:
        return html

    async def _replace_formulas_with_inline_svg(self, html: str) -> str:
        return html


class TestZujuanQuestionDetailRequest(unittest.IsolatedAsyncioTestCase):
    async def test_get_question_detail_uses_crawler_http_client(self) -> None:
        from backend.integrations.crawler.zujuan.detail import get_question_detail

        html = (
            '<span class="info-item">题型：单选题</span>'
            '<span class="info-item">难度：普通</span>'
            '<div class="quest-cnt ">测试题干</div><div class="quest-exam">'
            + ("x" * 10050)
        )
        crawler = DetailFakeCrawler(html)

        result = await get_question_detail(crawler, "123")

        self.assertTrue(result["success"])
        self.assertEqual(result["stem"], "测试题干")
        self.assertEqual(result["type"], "单选题")
        self.assertEqual(result["difficulty"], "普通")
        self.assertEqual(crawler.client.gets[0]["url"], "https://zujuan.xkw.com/15q123.html")
        self.assertEqual(crawler.client.gets[0]["headers"]["Referer"], "https://zujuan.xkw.com/")
        self.assertIn("text/html", crawler.client.gets[0]["headers"]["Accept"])
        self.assertEqual(crawler.client.gets[0]["timeout"], 30.0)

    async def test_get_question_detail_extracts_inline_answer_and_analysis(self) -> None:
        from backend.integrations.crawler.zujuan.detail import get_question_detail

        html = (
            '<span class="info-item">题型：填空题</span>'
            '<span class="info-item">难度：普通</span>'
            '<div class="quest-cnt ">测试题干</div><div class="quest-exam">'
            '<section>答案： 42</section><section>解析： 代入计算即可</section>'
            + ("x" * 10050)
        )
        crawler = DetailFakeCrawler(html)

        result = await get_question_detail(crawler, "456")

        self.assertTrue(result["success"])
        self.assertEqual(result["answer"], "42")
        self.assertEqual(result["analysis"], "代入计算即可")


class TestZujuanRegexHelpers(unittest.TestCase):
    def test_normalize_province_name_removes_actual_whitespace(self) -> None:
        from backend.integrations.crawler.zujuan.utils import _normalize_province_name

        self.assertEqual(_normalize_province_name(" 北 京 市 "), "北京")
        self.assertEqual(_normalize_province_name("内 蒙 古自治区"), "内蒙古")

    def test_blueprint_split_kps_splits_actual_newlines_and_tabs(self) -> None:
        from backend.integrations.crawler.zujuan.blueprint import _split_kps

        self.assertEqual(_split_kps("函数\n导数\t极值/应用"), ["函数", "导数", "极值", "应用"])


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


class TestZujuanCrawlerInitialization(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_defaults_to_visitor_mode_without_cookie_bootstrap(self) -> None:
        from backend.integrations.crawler.zujuan.client import ZujuanCrawler

        with (
            patch("backend.integrations.crawler.zujuan.client.load_env_login", return_value={"cookies": "userId=123", "is_logged_in": True}),
            patch("backend.integrations.crawler.zujuan.client.load_antibot_cookie_cache", return_value="aliyungf_tc=a; acw_tc=b"),
            patch("backend.integrations.crawler.zujuan.client.get_cookies_with_playwright", new_callable=AsyncMock) as get_cookies,
            patch.dict(
                "os.environ",
                {
                    "ZUJUAN_USE_ENV_COOKIES_FOR_SEARCH": "0",
                    "ZUJUAN_USE_CACHED_ANTIBOT_COOKIES": "0",
                    "ZUJUAN_AUTO_BOOTSTRAP_COOKIES": "0",
                },
                clear=False,
            ),
        ):
            crawler = ZujuanCrawler(subject="高中数学")
            await crawler.initialize()
            try:
                self.assertEqual(crawler.cookies, "")
                self.assertNotIn("Cookie", crawler.client.headers)
                get_cookies.assert_not_awaited()
            finally:
                await crawler.close()


if __name__ == "__main__":
    unittest.main()
