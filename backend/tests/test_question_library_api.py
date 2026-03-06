import unittest

from fastapi.testclient import TestClient

from backend.app import create_app


class TestQuestionLibraryApi(unittest.TestCase):
    def test_router_is_mounted(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/question-library/items")
        # Auth will block; we only assert that it's not a 404.
        self.assertNotEqual(resp.status_code, 404)

