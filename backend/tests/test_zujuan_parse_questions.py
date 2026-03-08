import unittest

from backend.crawler.zujuan.client import ZujuanCrawler


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
