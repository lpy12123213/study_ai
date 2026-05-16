from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from urllib.robotparser import RobotFileParser

from backend.crawler.rate_limiter import SQLiteTokenBucket
from backend.crawler.robots import RobotsDisallowedError, RobotsPolicy, RobotsTxtCache


class CrawlerRateLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_token_bucket_persists_shared_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "rate_limiter.sqlite")
            limiter = SQLiteTokenBucket(key="zujuan", rate_per_s=1000.0, burst=2, path=db_path)

            await limiter.acquire()

            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT tokens, updated_at_s FROM crawler_rate_limiter WHERE key = ?",
                    ("zujuan",),
                ).fetchone()

        self.assertIsNotNone(row)
        self.assertGreaterEqual(float(row[0]), 0.0)
        self.assertLess(float(row[0]), 2.0)
        self.assertGreater(float(row[1]), 0.0)


class RobotsTxtCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_robots_cache_blocks_disallowed_paths_and_reads_crawl_delay(self) -> None:
        parser = RobotFileParser()
        parser.set_url("https://example.com/robots.txt")
        parser.parse(
            [
                "User-agent: *",
                "Disallow: /private",
                "Crawl-delay: 2",
            ]
        )
        cache = RobotsTxtCache()
        cache.policies["https://example.com"] = RobotsPolicy(parser=parser, fetched_at_s=time.time())

        self.assertFalse(await cache.allowed("https://example.com/private/page", user_agent="StudyAI/1.0"))
        self.assertTrue(await cache.allowed("https://example.com/public/page", user_agent="StudyAI/1.0"))
        self.assertEqual(await cache.crawl_delay("https://example.com/", user_agent="StudyAI/1.0"), 2.0)

        with self.assertRaises(RobotsDisallowedError):
            await cache.assert_allowed("https://example.com/private/page", user_agent="StudyAI/1.0")


if __name__ == "__main__":
    unittest.main()
