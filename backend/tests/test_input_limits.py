"""Input-length safety tests that go through the FastAPI test client.

The auth store is now SQL-backed; we redirect the DB path to a tempfile and
reload the relevant modules so the bootstrap admin and the test user land in
that isolated database. The ``setUpClass`` snapshots and restores the auth
module cache so other tests in the suite are not affected.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

_RELOAD_MODULES = [
    "backend.app",
    "backend.api.auth",
    "backend.core.auth",
    "backend.database.repositories.system.auth_users",
    "backend.database.engine",
    "backend.database.paths",
]


class TestInputLengthLimits(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        tmp_root = repo_root / ".local" / "tmp" / "unittest"
        tmp_root.mkdir(parents=True, exist_ok=True)
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="input_limits_", dir=str(tmp_root))
        cls._original_db_path = os.environ.get("STUDY_AI_DB_PATH")
        os.environ["STUDY_AI_DB_PATH"] = str(Path(cls._tmpdir.name) / "input_limits.db")
        os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
        os.environ.setdefault("JWT_SECRET", "test-secret-32-bytes-minimum-length!!")

        cls._mod_snapshot = {name: sys.modules.get(name) for name in _RELOAD_MODULES}
        for name in _RELOAD_MODULES:
            sys.modules.pop(name, None)

        auth = importlib.import_module("backend.core.auth")
        app_mod = importlib.import_module("backend.app")

        user = auth.create_user("tester", "pw", role="user")
        assert user is not None
        token_ver = int(user.get("token_version") or 1)
        token = auth.create_access_token(
            {"user_id": user["user_id"], "username": user["username"], "role": "user", "ver": token_ver}
        )

        cls.client = TestClient(app_mod.create_app())
        cls.headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.client.close()
        except Exception:
            pass

        for name in _RELOAD_MODULES:
            sys.modules.pop(name, None)
        for name, mod in cls._mod_snapshot.items():
            if mod is not None:
                sys.modules[name] = mod

        try:
            cls._tmpdir.cleanup()
        except OSError:
            pass

        if cls._original_db_path is None:
            os.environ.pop("STUDY_AI_DB_PATH", None)
        else:
            os.environ["STUDY_AI_DB_PATH"] = cls._original_db_path

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
