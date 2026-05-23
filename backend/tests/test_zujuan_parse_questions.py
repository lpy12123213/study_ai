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
