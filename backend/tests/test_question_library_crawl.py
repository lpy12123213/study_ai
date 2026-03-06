import unittest

from fastapi.testclient import TestClient

from backend.app import create_app


class TestQuestionLibraryCrawl(unittest.TestCase):
    def test_crawl_endpoint_exists(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.post("/api/question-library/crawl", json={"subject": "高中数学", "query": "函数"})
        # NOTE: the app has a GET/HEAD SPA fallback route; unknown POST paths return 405.
        self.assertNotIn(resp.status_code, {404, 405})

    def test_task_stream_endpoint_exists(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/question-library/tasks/test-task/stream")
        self.assertNotEqual(resp.status_code, 404)
