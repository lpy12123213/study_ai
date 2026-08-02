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


class ResearchToolboxWikipediaTests(unittest.TestCase):
    def test_search_wikipedia_uses_wiki_channel_with_provider_label(self):
        calls = []

        async def fake_wiki(query, n):
            calls.append((query, n))
            return [{"url": "https://zh.wikipedia.org/wiki/x", "title": "t", "content": "s"}]

        box = ResearchToolbox(wiki_func=fake_wiki)
        out = asyncio.run(box.search_wikipedia("拉格朗日中值定理", n=3))
        self.assertEqual(calls, [("拉格朗日中值定理", 3)])
        self.assertEqual(out["provider"], "wikipedia")
        self.assertEqual(out["results"][0]["url"], "https://zh.wikipedia.org/wiki/x")

    def test_wikipedia_failure_raises_with_provider_name(self):
        async def boom(query, n):
            raise RuntimeError("api down")

        box = ResearchToolbox(wiki_func=boom)
        with self.assertRaises(RuntimeError) as cm:
            asyncio.run(box.search_wikipedia("q", n=1))
        self.assertIn("wikipedia", str(cm.exception))

    def test_default_wiki_adapter_shapes_integration_result(self):
        """默认 wiki 通道适配 backend.integrations.mcp.search.wikipedia.wikipedia_search（懒加载，可替身）。"""
        import backend.integrations.mcp.search.wikipedia as wiki_mod

        async def fake_search(query, **kwargs):
            self.assertEqual(query, "拉格朗日中值定理")
            return {
                "success": True,
                "title": "拉格朗日中值定理",
                "url": "https://zh.wikipedia.org/wiki/拉格朗日中值定理",
                "summary": "微分中值定理之一。",
                "content": "完整正文……",
                "provider": "wikipedia",
            }

        original = wiki_mod.wikipedia_search
        wiki_mod.wikipedia_search = fake_search
        try:
            out = asyncio.run(ResearchToolbox().search_wikipedia("拉格朗日中值定理", n=3))
        finally:
            wiki_mod.wikipedia_search = original
        self.assertEqual(out["provider"], "wikipedia")
        row = out["results"][0]
        self.assertEqual(row["url"], "https://zh.wikipedia.org/wiki/拉格朗日中值定理")
        self.assertEqual(row["content"], "微分中值定理之一。")

    def test_default_wiki_adapter_raises_on_integration_failure(self):
        import backend.integrations.mcp.search.wikipedia as wiki_mod

        async def fake_fail(query, **kwargs):
            return {"success": False, "error": "page missing", "provider": "wikipedia"}

        original = wiki_mod.wikipedia_search
        wiki_mod.wikipedia_search = fake_fail
        try:
            with self.assertRaises(RuntimeError) as cm:
                asyncio.run(ResearchToolbox().search_wikipedia("q", n=1))
        finally:
            wiki_mod.wikipedia_search = original
        self.assertIn("wikipedia", str(cm.exception))
        self.assertIn("page missing", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
