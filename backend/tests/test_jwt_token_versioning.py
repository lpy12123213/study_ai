"""JWT versioning regression test against the (now DB-backed) auth store."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_AUTH_MODULES = [
    "backend.api.auth",
    "backend.app",
    "backend.core.auth",
    "backend.database.repositories.system.auth_users",
    "backend.database.engine",
    "backend.database.paths",
]


class TestJwtTokenVersioning(unittest.TestCase):
    """Changing a password must invalidate any previously issued JWT for that user.

    The store is now SQL-backed. We point ``STUDY_AI_DB_PATH`` at an isolated
    sqlite file so the test does not touch the developer's local DB.
    """

    @classmethod
    def setUpClass(cls) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        tmp_root = repo_root / ".local" / "tmp" / "unittest"
        tmp_root.mkdir(parents=True, exist_ok=True)
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="jwt_ver_", dir=str(tmp_root))
        cls._original_db_path = os.environ.get("STUDY_AI_DB_PATH")
        os.environ["STUDY_AI_DB_PATH"] = str(Path(cls._tmpdir.name) / "auth.db")
        cls._original_admin_pw = os.environ.get("ADMIN_PASSWORD")
        os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
        os.environ.setdefault("JWT_SECRET", "test-secret-32-bytes-minimum-length!!")

        # Snapshot then drop module cache so backend.core.auth re-evaluates
        # ``resolve_db_path`` against the override above.
        cls._mod_snapshot = {name: sys.modules.get(name) for name in _AUTH_MODULES}
        for name in _AUTH_MODULES:
            sys.modules.pop(name, None)
        cls._auth = importlib.import_module("backend.core.auth")

    @classmethod
    def tearDownClass(cls) -> None:
        # Restore the previously cached modules so other tests run against the
        # original DB / module identity.
        for name in _AUTH_MODULES:
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

    def test_password_change_invalidates_old_token(self) -> None:
        auth = self._auth
        with patch.object(auth, "JWT_SECRET", "test-secret-32-bytes-minimum-length!!"):
            user = auth.create_user("alice", "oldpw", role="user")
            self.assertIsNotNone(user)
            assert user is not None

            user_id = str(user["user_id"])
            username = str(user["username"])
            token_ver_1 = int(user.get("token_version") or 1)

            token_1 = auth.create_access_token(
                {"user_id": user_id, "username": username, "role": "user", "ver": token_ver_1}
            )
            self.assertIsNotNone(auth.validate_access_token(token_1))

            ok = auth.change_user_password(username, "oldpw", "newpw")
            self.assertTrue(ok)
            self.assertIsNone(auth.validate_access_token(token_1))

            user2 = auth.get_user_by_username(username)
            self.assertIsNotNone(user2)
            assert user2 is not None
            token_ver_2 = int(user2.get("token_version") or 1)

            token_2 = auth.create_access_token(
                {"user_id": user_id, "username": username, "role": "user", "ver": token_ver_2}
            )
            self.assertIsNotNone(auth.validate_access_token(token_2))
