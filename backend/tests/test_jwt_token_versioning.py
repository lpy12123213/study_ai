from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backend.core.auth as auth


class TestJwtTokenVersioning(unittest.TestCase):
    def test_password_change_invalidates_old_token(self) -> None:
        original_users = dict(auth._users)
        original_revoked = dict(auth._revoked_tokens)

        try:
            # Windows sandbox environments sometimes deny deleting system-temp folders (WinError 5).
            # Keep test tmp under project-local `.local/` and do best-effort cleanup.
            repo_root = Path(__file__).resolve().parents[2]
            tmp_root = repo_root / ".local" / "tmp" / "unittest"
            tmp_root.mkdir(parents=True, exist_ok=True)
            tmpdir = tempfile.mkdtemp(dir=str(tmp_root))
            try:
                tmp = Path(tmpdir)
                with patch.object(auth, "LOCAL_DIR", tmp):
                    with patch.object(auth, "USERS_PATH", tmp / "users.json"):
                        with patch.object(auth, "REVOKED_TOKENS_PATH", tmp / "jwt_revoked.json"):
                            with patch.object(auth, "JWT_SECRET", "test-secret-32-bytes-minimum-length!!"):
                                auth._users.clear()
                                auth._revoked_tokens.clear()

                                user = auth.create_user("alice", "oldpw", role="user")
                                self.assertIsNotNone(user)

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
                                token_ver_2 = int(user2.get("token_version") or 1)

                                token_2 = auth.create_access_token(
                                    {"user_id": user_id, "username": username, "role": "user", "ver": token_ver_2}
                                )
                                self.assertIsNotNone(auth.validate_access_token(token_2))
            finally:
                try:
                    shutil.rmtree(tmpdir, ignore_errors=True)
                except OSError:
                    pass
        finally:
            auth._users.clear()
            auth._users.update(original_users)
            auth._revoked_tokens.clear()
            auth._revoked_tokens.update(original_revoked)
