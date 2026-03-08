from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.auth as auth
from backend.app import create_app


class TestInputLengthLimits(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._original_users = dict(auth._users)
        cls._original_revoked = dict(auth._revoked_tokens)
        cls._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmpdir.name)

        cls._patchers = [
            patch.object(auth, "LOCAL_DIR", tmp),
            patch.object(auth, "USERS_PATH", tmp / "users.json"),
            patch.object(auth, "REVOKED_TOKENS_PATH", tmp / "jwt_revoked.json"),
            patch.object(auth, "JWT_SECRET", "test-secret-32-bytes-minimum-length!!"),
        ]
        for p in cls._patchers:
            p.start()

        auth._users.clear()
        auth._revoked_tokens.clear()

        user = auth.create_user("tester", "pw", role="user")
        assert user is not None
        token_ver = int(user.get("token_version") or 1)
        token = auth.create_access_token(
            {"user_id": user["user_id"], "username": user["username"], "role": "user", "ver": token_ver}
        )

        cls.client = TestClient(create_app())
        cls.headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            for p in reversed(getattr(cls, "_patchers", [])):
                p.stop()
            tmpdir = getattr(cls, "_tmpdir", None)
            if tmpdir is not None:
                tmpdir.cleanup()
        finally:
            auth._users.clear()
            auth._users.update(getattr(cls, "_original_users", {}))
            auth._revoked_tokens.clear()
            auth._revoked_tokens.update(getattr(cls, "_original_revoked", {}))

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
