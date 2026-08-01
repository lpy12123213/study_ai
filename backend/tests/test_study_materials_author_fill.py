import asyncio
import unittest

from backend.generation.study_materials.author.blueprint import Blueprint
from backend.generation.study_materials.author.fill import FillRunner

BP = Blueprint.from_dict({
    "narrative": "n", "terminology": [{"symbol": "$\\epsilon$", "meaning": "任意小"}],
    "sections": [{"id": "sec-1", "title": "t", "purpose": "p", "key_points": ["k"],
                  "target_chars": 800, "difficulty": "基础", "misconceptions": [],
                  "frontier": False}],
    "figures": [],
})


class FillRunnerTests(unittest.TestCase):
    def test_context_pack_is_bounded_and_grounded(self):
        seen = {}

        async def fake_llm(system, user):
            seen["user"] = user
            return "正文含 $\\epsilon$。[EX1] 例 …[Q1] 题 …[A1] 答 …"

        r = FillRunner(llm_func=fake_llm, max_retries=2)
        out = asyncio.run(r.fill(BP.sections[0], backbone_excerpt="衔接段",
                                 research_slice="fact: x | src: https://a",
                                 terminology=BP.terminology))
        self.assertIn("$\\epsilon$", out.text)
        self.assertIn("衔接段", seen["user"])          # 知道接在哪
        self.assertIn("https://a", seen["user"])       # 笔记切片注入
        self.assertLess(len(seen["user"]), 12000)      # 有界

    def test_retry_then_author_fallback_flag(self):
        async def bad_llm(system, user):
            return "太短"

        r = FillRunner(llm_func=bad_llm, max_retries=2, min_chars=100)
        out = asyncio.run(r.fill(BP.sections[0], backbone_excerpt="",
                                 research_slice="", terminology=[]))
        self.assertTrue(out.needs_author_rewrite)
        self.assertEqual(out.attempts, 2)

    def test_url_in_output_rejected(self):
        async def leaky_llm(system, user):
            return "见 https://example.com 详情……" * 20

        r = FillRunner(llm_func=leaky_llm, max_retries=1, min_chars=10)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))
        self.assertTrue(out.needs_author_rewrite)


if __name__ == "__main__":
    unittest.main()
