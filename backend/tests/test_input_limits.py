from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.auth import create_access_token


class TestInputLengthLimits(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        token = create_access_token({"user_id": "test-user", "username": "tester", "role": "user"})
        cls.client = TestClient(create_app())
        cls.headers = {"Authorization": f"Bearer {token}"}

    def test_chat_rejects_oversized_message_with_400(self) -> None:
        response = self.client.post(
            "/api/chat",
            headers=self.headers,
            json={"conversation_id": 1, "message": "x" * 12001},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "message_too_long")

    def test_deepthink_rejects_oversized_question_with_400(self) -> None:
        response = self.client.post(
            "/api/deepthink",
            headers=self.headers,
            json={"question": "x" * 12001},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "question_too_long")

    def test_study_materials_rejects_oversized_query_with_400(self) -> None:
        response = self.client.post(
            "/api/study-materials/generate",
            headers=self.headers,
            json={"query": "x" * 2001},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "query_too_long")

    def test_markdown_to_latex_rejects_oversized_markdown_with_400(self) -> None:
        response = self.client.post(
            "/api/study-materials/convert-markdown-to-latex",
            headers=self.headers,
            json={"markdown": "x" * 120001},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "markdown_too_long")
