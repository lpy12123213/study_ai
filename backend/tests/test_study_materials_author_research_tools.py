import asyncio
import unittest

from backend.generation.study_materials.author.research_tools import ResearchToolbox


class ResearchToolboxTests(unittest.TestCase):
    def test_search_calls_provider_directly_without_llm(self):
        calls = []

        async def fake_serp(query, n):
            calls.append(query)
            return [{"url": "https://a/x", "title": "t", "snippet": "s"}]

        box = ResearchToolbox(serp_func=fake_serp)
        out = asyncio.run(box.search("拉格朗日 中值定理 常见错误", n=3))
        self.assertEqual(calls, ["拉格朗日 中值定理 常见错误"])
        self.assertEqual(out["results"][0]["url"], "https://a/x")
        self.assertNotIn("sub_questions", out)  # 无 decompose 层

    def test_provider_failure_raises_with_provider_name(self):
        async def boom(query, n):
            raise RuntimeError("http_status_432")

        box = ResearchToolbox(serp_func=boom)
        with self.assertRaises(RuntimeError) as cm:
            asyncio.run(box.search("q", n=1))
        self.assertIn("serp", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
