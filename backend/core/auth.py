"""
Authentication utilities for JWT token handling.

State that used to live in module-level dicts + ``.local/users.json`` /
``.local/jwt_revoked.json`` snapshots is now persisted in the SQL DB via
``backend.database.repositories.system.auth_users``. That move is required for
multi-worker deployments: previously each uvicorn worker held its own copy of
``_users`` and never noticed registrations / password changes / token
revocations issued by sibling workers.

The public function names are unchanged so ``backend.api.auth`` and existing
tests keep working without per-call refactors.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import jwt

from backend.core.logging_utils import get_logger
from backend.core.settings import load_project_dotenv
from backend.database.repositories.system import auth_users as _user_repo

load_project_dotenv(override=False)

# File lives in `backend/core/`; repo root is 3 levels up.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCAL_DIR = PROJECT_ROOT / ".local"
USERS_PATH = LOCAL_DIR / "users.json"
REVOKED_TOKENS_PATH = LOCAL_DIR / "jwt_revoked.json"
_bootstrap_lock = threading.RLock()
logger = get_logger(__name__)


def _load_jwt_secret_from_env() -> str:
    env_secret = (os.getenv("JWT_SECRET") or "").strip()
    if env_secret:
        return env_secret

    raise ValueError("JWT_SECRET is required (set it in environment or .env).")


def _get_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.

    Delegates to the canonical helper in :mod:`backend.core.security.password`
    so every entry point uses the same cost factor and bytes-handling.
    """

    from backend.core.security.password import hash_password as _hash

    return _hash(password)


def _legacy_sha256(password: str) -> str:
    """Legacy SHA256 hash for migration check only."""
    return hashlib.sha256((password or "").encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash.

    Supports both bcrypt (new) and SHA256 (legacy).
    If a legacy hash matches, it is automatically upgraded to bcrypt by the
    caller (see :func:`authenticate_user`).
    """
    # Try bcrypt first (new format starts with $2b$ / $2a$).
    if password_hash.startswith("$2b$") or password_hash.startswith("$2a$"):
        from backend.core.security.password import verify_password as _verify

        return _verify(password, password_hash)

    # Fallback: legacy SHA256 (64 hex chars).
    if len(password_hash) == 64:
        return _legacy_sha256(password) == password_hash

    return False


def _admin_settings() -> Dict[str, Any]:
    username = (os.getenv("ADMIN_USERNAME") or "admin").strip() or "admin"
    role = (os.getenv("ADMIN_ROLE") or "admin").strip() or "admin"

    explicit_hash = (os.getenv("ADMIN_PASSWORD_HASH") or "").strip()
    if explicit_hash:
        return {
            "user_id": "1",
            "username": username,
            "role": role,
            "password_hash": explicit_hash,
            "force_password_hash": explicit_hash,
        }

    password = (os.getenv("ADMIN_PASSWORD") or "").strip()
    if not password:
        raise ValueError("ADMIN_PASSWORD is required (or set ADMIN_PASSWORD_HASH).")

    return {
        "user_id": "1",
        "username": username,
        "role": role,
        # Initial bootstrap hash; not forced (keeps user-changed passwords).
        "password_hash": hash_password(password),
        "force_password_hash": None,
    }


def _migrate_local_snapshot_into_db() -> None:
    """One-shot import of legacy ``.local/users.json`` + ``.local/jwt_revoked.json``.

    This handles installs that upgraded *without* running alembic (the alembic
    revision performs the same migration). Both code paths use ``INSERT OR
    IGNORE`` semantics, so re-running is safe.
    """

    try:
        if USERS_PATH.exists():
            raw = USERS_PATH.read_text(encoding="utf-8")
            obj = json.loads(raw) if raw.strip() else {}
            if isinstance(obj, dict):
                for username, user in obj.items():
                    if not isinstance(user, dict):
                        continue
                    uid = str(user.get("user_id") or "").strip()
                    uname = str(username or user.get("username") or "").strip()
                    if not uid or not uname:
                        continue
                    if _user_repo.get_user_by_username(uname) is not None:
                        continue
                    _user_repo.insert_user(
                        user_id=uid,
                        username=uname,
                        password_hash=str(user.get("password_hash") or ""),
                        role=str(user.get("role") or "user"),
                        token_version=int(user.get("token_version") or 1),
                    )
    except (OSError, ValueError, json.JSONDecodeError):
        logger.warning("auth_users_local_snapshot_import_failed", exc_info=True)

    try:
        if REVOKED_TOKENS_PATH.exists():
            raw = REVOKED_TOKENS_PATH.read_text(encoding="utf-8")
            obj = json.loads(raw) if raw.strip() else {}
            if isinstance(obj, dict):
                for jti, exp_ts in obj.items():
                    if not isinstance(jti, str) or not jti.strip():
                        continue
                    try:
                        _user_repo.revoke_jti(jti.strip(), int(exp_ts or 0))
                    except (TypeError, ValueError):
                        continue
    except (OSError, ValueError, json.JSONDecodeError):
        logger.warning("auth_revoked_tokens_local_snapshot_import_failed", exc_info=True)


def _bootstrap_admin_once() -> None:
    """Ensure the admin row exists. Safe to call on every import."""

    with _bootstrap_lock:
        try:
            settings = _admin_settings()
        except ValueError:
            # ``ADMIN_PASSWORD`` is enforced at module import in production but
            # tests sometimes import without it set; surface the same error
            # only when the caller actually tries to authenticate.
            raise

        try:
            _user_repo.ensure_admin_row(
                user_id=str(settings["user_id"]),
                username=str(settings["username"]),
                password_hash=str(settings["password_hash"]),
                role=str(settings.get("role") or "admin"),
                force_password_hash=settings.get("force_password_hash"),
            )
        except Exception:
            logger.warning("auth_admin_bootstrap_failed", exc_info=True)


# JWT settings
JWT_SECRET = _load_jwt_secret_from_env()
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = _get_int_env("JWT_EXPIRE_HOURS", 24)


# Best-effort one-shot migration of the legacy snapshots, then bootstrap admin.
# We swallow exceptions: if the DB schema isn't ready yet (e.g. the very first
# boot before ``init_db()``), the bootstrap will retry on the next call.
try:
    _migrate_local_snapshot_into_db()
    _bootstrap_admin_once()
except Exception:
    logger.warning("auth_initial_bootstrap_failed", exc_info=True)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=JWT_EXPIRE_HOURS))
    if not to_encode.get("jti"):
        to_encode["jti"] = uuid.uuid4().hex
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def revoke_token_jti(*, jti: str, exp_ts: int) -> None:
    _user_repo.revoke_jti(str(jti or "").strip(), int(exp_ts or 0))


def is_token_revoked(jti: str) -> bool:
    return _user_repo.is_jti_revoked(str(jti or "").strip())


def validate_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Validate token signature, expiry, user binding, token version and revocation."""

    payload = decode_token(token)
    if not payload:
        return None

    user_id = str(payload.get("user_id") or "").strip()
    username = str(payload.get("username") or "").strip()
    if not user_id or not username:
        return None

    user = _user_repo.get_user_by_username(username)
    if not user:
        return None
    if str(user.get("user_id") or "").strip() != user_id:
        return None
    try:
        token_ver = int(payload.get("ver") or payload.get("token_version") or 1)
    except (TypeError, ValueError):
        token_ver = 1
    try:
        user_ver = int(user.get("token_version") or 1)
    except (TypeError, ValueError):
        user_ver = 1
    if token_ver != user_ver:
        return None

    jti = str(payload.get("jti") or "").strip()
    if jti and is_token_revoked(jti):
        return None

    return payload


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Get user by username."""

    return _user_repo.get_user_by_username(username)


def create_user(username: str, password: str, role: str = "user") -> Optional[Dict[str, Any]]:
    """Create a new user. Returns ``None`` when the username is already taken."""

    uname = (username or "").strip()
    if not uname:
        return None
    if _user_repo.get_user_by_username(uname) is not None:
        return None

    user_id = uuid.uuid4().hex
    ok = _user_repo.insert_user(
        user_id=user_id,
        username=uname,
        password_hash=hash_password(password),
        role=(role or "user").strip() or "user",
        token_version=1,
    )
    if not ok:
        return None
    return _user_repo.get_user_by_username(uname)


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate a user with username and password.

    Auto-upgrades legacy SHA256 hashes to bcrypt on successful login.
    """

    user = get_user_by_username(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None

    # Auto-upgrade legacy SHA256 hash to bcrypt without rotating token_version.
    ph = user["password_hash"]
    if not (ph.startswith("$2b$") or ph.startswith("$2a$")):
        new_hash = hash_password(password)
        _user_repo.upgrade_password_hash(username=user["username"], password_hash=new_hash)
        user = _user_repo.get_user_by_username(user["username"]) or user

    return user


def get_all_users() -> list[Dict[str, Any]]:
    """Get all users (admin only)."""

    return [
        {
            "user_id": u["user_id"],
            "username": u["username"],
            "role": u["role"],
            "created_at": u.get("created_at"),
        }
        for u in _user_repo.list_users()
    ]


def change_user_password(username: str, old_password: str, new_password: str) -> bool:
    """Change user password (rotates ``token_version`` so old JWTs invalidate)."""

    uname = (username or "").strip()
    if not uname:
        return False

    user = _user_repo.get_user_by_username(uname)
    if not user:
        return False
    if not verify_password(old_password, user["password_hash"]):
        return False

    ok, _new_ver = _user_repo.update_password_and_bump_version(
        username=uname,
        password_hash=hash_password(new_password),
    )
    return bool(ok)
