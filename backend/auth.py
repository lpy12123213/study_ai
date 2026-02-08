"""
Authentication utilities for JWT token handling.
"""

from __future__ import annotations

import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import jwt
from dotenv import load_dotenv

load_dotenv(override=False)

def _get_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default

def hash_password(password: str) -> str:
    """Hash a password using SHA256."""
    return hashlib.sha256((password or "").encode()).hexdigest()


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


# JWT settings
JWT_SECRET = (os.getenv("JWT_SECRET") or "").strip() or secrets.token_hex(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = _get_int_env("JWT_EXPIRE_HOURS", 24)

# Simple in-memory user store (replace with database in production)
_admin_user = _load_admin_user()
_users: Dict[str, Dict[str, Any]] = {
    _admin_user["username"]: _admin_user,
}


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return hash_password(password) == password_hash


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=JWT_EXPIRE_HOURS))
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
    return _users.get(username)


def create_user(username: str, password: str, role: str = "user") -> Optional[Dict[str, Any]]:
    """Create a new user."""
    if username in _users:
        return None
    
    user_id = str(len(_users) + 1)
    user = {
        "user_id": user_id,
        "username": username,
        "password_hash": hash_password(password),
        "role": role,
        "created_at": datetime.now().isoformat(),
    }
    _users[username] = user
    return user


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate a user with username and password."""
    user = get_user_by_username(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
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
        for u in _users.values()
    ]


def change_user_password(username: str, old_password: str, new_password: str) -> bool:
    """Change user password."""
    user = get_user_by_username(username)
    if not user:
        return False
    if not verify_password(old_password, user["password_hash"]):
        return False
    user["password_hash"] = hash_password(new_password)
    return True
