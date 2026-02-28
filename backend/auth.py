"""
Authentication utilities for JWT token handling.
"""

from __future__ import annotations

import json
import os
import hashlib
import secrets
import threading
import uuid
from datetime import datetime, timedelta
from datetime import timezone
from pathlib import Path
from typing import Optional, Dict, Any

import bcrypt
import jwt
from dotenv import load_dotenv

load_dotenv(override=False)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = PROJECT_ROOT / ".local"
JWT_SECRET_PATH = LOCAL_DIR / "jwt_secret.txt"
USERS_PATH = LOCAL_DIR / "users.json"
_users_lock = threading.RLock()


def _load_or_create_jwt_secret() -> str:
    env_secret = (os.getenv("JWT_SECRET") or "").strip()
    if env_secret:
        return env_secret

    try:
        if JWT_SECRET_PATH.exists():
            saved = JWT_SECRET_PATH.read_text(encoding="utf-8").strip()
            if saved:
                return saved
    except Exception:
        saved = ""

    secret = secrets.token_hex(32)
    try:
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        JWT_SECRET_PATH.write_text(secret, encoding="utf-8")
    except Exception:
        pass
    return secret

def _get_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw((password or "").encode(), bcrypt.gensalt()).decode()


def _legacy_sha256(password: str) -> str:
    """Legacy SHA256 hash for migration check only."""
    return hashlib.sha256((password or "").encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash.

    Supports both bcrypt (new) and SHA256 (legacy).
    If a legacy hash matches, it is automatically upgraded to bcrypt.
    """
    # Try bcrypt first (new format starts with $2b$)
    if password_hash.startswith("$2b$") or password_hash.startswith("$2a$"):
        return bcrypt.checkpw((password or "").encode(), password_hash.encode())

    # Fallback: legacy SHA256 (64 hex chars)
    if len(password_hash) == 64:
        return _legacy_sha256(password) == password_hash

    return False


def _load_admin_user() -> Dict[str, Any]:
    username = (os.getenv("ADMIN_USERNAME") or "admin").strip() or "admin"
    role = (os.getenv("ADMIN_ROLE") or "admin").strip() or "admin"

    password_hash = (os.getenv("ADMIN_PASSWORD_HASH") or "").strip()
    if not password_hash:
        password = os.getenv("ADMIN_PASSWORD", "admin123")
        password_hash = hash_password(password)

    return {
        "user_id": "1",
        "username": username,
        "password_hash": password_hash,
        "role": role,
        "created_at": datetime.now().isoformat(),
    }


def _load_users_from_disk() -> Dict[str, Dict[str, Any]]:
    try:
        if not USERS_PATH.exists():
            return {}
        raw = USERS_PATH.read_text(encoding="utf-8")
        obj = json.loads(raw) if raw.strip() else {}
        if not isinstance(obj, dict):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in obj.items():
            if not isinstance(k, str) or not isinstance(v, dict):
                continue
            out[k] = dict(v)
        return out
    except Exception:
        return {}


def _save_users_to_disk(users: Dict[str, Dict[str, Any]]) -> None:
    try:
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        tmp = USERS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(USERS_PATH)
    except Exception:
        return


def _bootstrap_users() -> Dict[str, Dict[str, Any]]:
    users = _load_users_from_disk()
    admin = _load_admin_user()
    admin_username = str(admin.get("username") or "admin").strip() or "admin"

    existing = users.get(admin_username)
    if isinstance(existing, dict):
        existing = dict(existing)
        existing.setdefault("user_id", admin.get("user_id") or "1")
        existing.setdefault("created_at", admin.get("created_at") or datetime.now().isoformat())
        existing["role"] = str(existing.get("role") or admin.get("role") or "admin")

        admin_hash_env = (os.getenv("ADMIN_PASSWORD_HASH") or "").strip()
        admin_pw_env = (os.getenv("ADMIN_PASSWORD") or "").strip()
        if admin_hash_env or admin_pw_env:
            existing["password_hash"] = admin.get("password_hash")
        users[admin_username] = existing
    else:
        users[admin_username] = admin

    _save_users_to_disk(users)
    return users


# JWT settings
JWT_SECRET = _load_or_create_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = _get_int_env("JWT_EXPIRE_HOURS", 24)

# Simple in-memory user store (replace with database in production)
_users: Dict[str, Dict[str, Any]] = _bootstrap_users()


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=JWT_EXPIRE_HOURS))
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


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Get user by username."""
    with _users_lock:
        return _users.get(username)


def create_user(username: str, password: str, role: str = "user") -> Optional[Dict[str, Any]]:
    """Create a new user."""
    uname = (username or "").strip()
    if not uname:
        return None

    with _users_lock:
        if uname in _users:
            return None

        user_id = uuid.uuid4().hex
        user = {
            "user_id": user_id,
            "username": uname,
            "password_hash": hash_password(password),
            "role": (role or "user").strip() or "user",
            "created_at": datetime.now().isoformat(),
        }
        _users[uname] = user
        _save_users_to_disk(_users)
        return user


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate a user with username and password.

    Auto-upgrades legacy SHA256 hashes to bcrypt on successful login.
    """
    user = get_user_by_username(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None

    # Auto-upgrade legacy SHA256 hash to bcrypt
    ph = user["password_hash"]
    if not (ph.startswith("$2b$") or ph.startswith("$2a$")):
        with _users_lock:
            user["password_hash"] = hash_password(password)
            _save_users_to_disk(_users)

    return user


def get_all_users() -> list[Dict[str, Any]]:
    """Get all users (admin only)."""
    with _users_lock:
        return [
            {
                "user_id": u["user_id"],
                "username": u["username"],
                "role": u["role"],
                "created_at": u.get("created_at"),
            }
            for u in _users.values()
        ]


def change_user_password(username: str, old_password: str, new_password: str) -> bool:
    """Change user password."""
    uname = (username or "").strip()
    if not uname:
        return False

    with _users_lock:
        user = _users.get(uname)
        if not user:
            return False
        if not verify_password(old_password, user["password_hash"]):
            return False
        user["password_hash"] = hash_password(new_password)
        _save_users_to_disk(_users)
        return True
