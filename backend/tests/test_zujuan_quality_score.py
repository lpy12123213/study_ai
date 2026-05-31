import unittest


class TestZujuanQualityScore(unittest.TestCase):
    def setUp(self) -> None:
        from backend.integrations.crawler.zujuan_crawler import ZujuanCrawler

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

    def test_infers_choice_prompt_without_type(self) -> None:
        q = {
            "type": "综合题",
            "knowledge_points": ["弹簧", "动量"],
            "stem": "如图所示，A、B两个物体之间用轻弹簧连接，放在光滑水平面上，则（　　）",
        }
        score, flags = self.crawler._quality_score(q)
        self.assertIn("choice_missing_options", flags)
        self.assertLess(score, 80)

    def test_inferred_choice_with_embedded_options(self) -> None:
        q = {
            "type": "综合题",
            "knowledge_points": ["弹簧", "动量"],
            "stem": (
                "如图所示，A、B两个物体之间用轻弹簧连接，放在光滑水平面上，"
                "从静止释放后判断系统运动情况，则（　　） A．甲 B．乙 C．丙 D．丁"
            ),
        }
        score, flags = self.crawler._quality_score(q)
        self.assertTrue(any(str(f).startswith("choice_options:") for f in flags))
        self.assertNotIn("choice_missing_options", flags)
        self.assertGreaterEqual(score, 80)

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
