from __future__ import annotations

import unittest

from backend.crawler.zujuan.client import ZujuanCrawler


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
