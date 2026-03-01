import inspect
import os
import tempfile
import unittest
from pathlib import Path


class CrawlerRecordReplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._env_before = dict(os.environ)
        self._tmp = tempfile.TemporaryDirectory()

        # Enable replay globally for these tests.
        os.environ["REPLAY"] = "1"
        os.environ.pop("RECORD", None)
        os.environ.pop("RECORD_REPLAY_MODE", None)

        from backend.crawler.zujuan import client as crawler_client

        self._crawler_client = crawler_client
        self._orig_root = getattr(crawler_client._record_replay_store, "_root", None)
        crawler_client._record_replay_store._root = Path(self._tmp.name)

    def tearDown(self) -> None:
        try:
            if self._orig_root is not None:
                self._crawler_client._record_replay_store._root = self._orig_root
        finally:
            self._tmp.cleanup()
            os.environ.clear()
            os.environ.update(self._env_before)

    async def test_search_by_keyword_uses_replay_fixture(self) -> None:
        from backend.crawler.zujuan.client import ZujuanCrawler, _record_replay_store

        crawler = ZujuanCrawler(subject="高中数学")

        sig = inspect.signature(ZujuanCrawler.search_by_keyword)
        kwargs = {
            name: param.default
            for name, param in sig.parameters.items()
            if name != "self" and param.default is not inspect._empty
        }
        kwargs["keyword"] = "函数单调性"

        req = crawler._record_replay_request("search_by_keyword", kwargs)
        _record_replay_store.save(
            request=req,
            response={"success": True, "questions": [{"question_id": "q1", "stem": "x"}]},
            meta={"note": "unittest"},
        )

        res = await crawler.search_by_keyword(keyword="函数单调性")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("questions")[0].get("question_id"), "q1")
        self.assertEqual((res.get("record_replay") or {}).get("mode"), "replay")

    async def test_get_question_detail_uses_replay_fixture(self) -> None:
        from backend.crawler.zujuan.client import ZujuanCrawler, _record_replay_store

        crawler = ZujuanCrawler(subject="高中数学")

        sig = inspect.signature(ZujuanCrawler.get_question_detail)
        kwargs = {
            name: param.default
            for name, param in sig.parameters.items()
            if name != "self" and param.default is not inspect._empty
        }
        kwargs["question_id"] = "12345"

        req = crawler._record_replay_request("get_question_detail", kwargs)
        _record_replay_store.save(
            request=req,
            response={"success": True, "question_id": "12345", "stem": "hello"},
            meta={"note": "unittest"},
        )

        res = await crawler.get_question_detail("12345")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("question_id"), "12345")
        self.assertEqual((res.get("record_replay") or {}).get("mode"), "replay")


if __name__ == "__main__":
    unittest.main()

