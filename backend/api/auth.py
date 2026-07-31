"""Authentication API endpoints."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.api.auth_schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserInfo,
    UserListResponse,
)
from backend.core.audit import AuditAction, audit_logger
from backend.core.auth import (
    JWT_EXPIRE_HOURS,
    authenticate_user,
    change_user_password,
    create_access_token,
    create_user,
    get_all_users,
    revoke_token_jti,
    validate_access_token,
)
from backend.core.settings import env_int

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)
AUTH_ACCESS_COOKIE_NAME = "study_ai_access_token"


def _truthy(raw: str) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _auth_cookie_secure() -> bool:
    raw = os.getenv("AUTH_COOKIE_SECURE")
    if raw is not None:
        return _truthy(raw)
    env = (os.getenv("ENV") or os.getenv("APP_ENV") or "").strip().lower()
    return env in {"prod", "production"}


class _LoginAttemptLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def reset(self) -> None:
        self._attempts.clear()
        self._locked_until.clear()

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        until = float(self._locked_until.get(key) or 0.0)
        if until <= now:
            self._locked_until.pop(key, None)
            return 0
        return max(1, int(round(until - now)))

    def record_failure(self, key: str) -> int:
        max_failures = env_int("AUTH_LOGIN_MAX_FAILURES", 5)
        window_s = env_int("AUTH_LOGIN_WINDOW_S", 300)
        lock_s = env_int("AUTH_LOGIN_LOCK_S", 300)
        if max_failures <= 0 or window_s <= 0 or lock_s <= 0:
            return 0

        now = time.monotonic()
        recent = [ts for ts in self._attempts.get(key, []) if now - ts <= window_s]
        recent.append(now)
        self._attempts[key] = recent
        if len(recent) <= max_failures:
            return 0
        self._locked_until[key] = now + lock_s
        return lock_s

    def record_success(self, key: str) -> None:
        self._attempts.pop(key, None)
        self._locked_until.pop(key, None)


_login_attempt_limiter = _LoginAttemptLimiter()



def _request_ip(req: Request) -> str:
    return str(getattr(req.client, "host", "") or "").strip()


def _login_limiter_key(payload: LoginRequest, http_request: Request) -> str:
    username = str(getattr(payload, "username", "") or "").strip().lower()
    return f"{_request_ip(http_request)}:{username}"


def _raise_login_locked(*, payload: LoginRequest, http_request: Request, retry_after_s: int) -> None:
    audit_logger.log(
        user_id="",
        action=AuditAction.LOGIN_BRUTE_FORCE,
        resource="/api/auth/login",
        ip=_request_ip(http_request),
        details={"username": str(getattr(payload, "username", "") or "").strip()},
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="login_locked",
        headers={"Retry-After": str(max(1, int(retry_after_s or 1)))},
    )


def _set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        AUTH_ACCESS_COOKIE_NAME,
        token,
        max_age=max(1, int(JWT_EXPIRE_HOURS or 24)) * 3600,
        httponly=True,
        secure=_auth_cookie_secure(),
        samesite="lax",
        path="/",
    )


def _clear_access_cookie(response: Response) -> None:
    response.delete_cookie(
        AUTH_ACCESS_COOKIE_NAME,
        httponly=True,
        secure=_auth_cookie_secure(),
        samesite="lax",
        path="/",
    )


def _token_from_request(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
) -> str:
    if credentials and credentials.credentials:
        return str(credentials.credentials or "").strip()
    try:
        return str(request.cookies.get(AUTH_ACCESS_COOKIE_NAME) or "").strip()
    except AttributeError:
        return ""


def local_auth_user() -> dict:
    """Return the built-in local user used when login is disabled."""

    return {
        "user_id": "local-user",
        "username": "本地用户",
        "role": "admin",
        "auth_source": "local",
    }


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, http_request: Request, response: Response) -> LoginResponse:
    """Authenticate a user and return a JWT."""

    limiter_key = _login_limiter_key(payload, http_request)
    retry_after_s = _login_attempt_limiter.retry_after(limiter_key)
    if retry_after_s > 0:
        _raise_login_locked(payload=payload, http_request=http_request, retry_after_s=retry_after_s)

    user = authenticate_user(payload.username, payload.password)
    if not user:
        audit_logger.log(
            user_id="",
            action=AuditAction.LOGIN_FAILED,
            resource="/api/auth/login",
            ip=_request_ip(http_request),
            details={"username": str(payload.username or "").strip()},
        )
        retry_after_s = _login_attempt_limiter.record_failure(limiter_key)
        if retry_after_s > 0:
            _raise_login_locked(payload=payload, http_request=http_request, retry_after_s=retry_after_s)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    _login_attempt_limiter.record_success(limiter_key)
    expires_delta = timedelta(hours=JWT_EXPIRE_HOURS)
    expires_at = int((datetime.now(timezone.utc) + expires_delta).timestamp())
    token = create_access_token(
        {
            "user_id": user["user_id"],
            "username": user["username"],
            "role": user.get("role") or "user",
            "ver": int(user.get("token_version") or 1),
        },
        expires_delta=expires_delta,
    )
    audit_logger.log(
        user_id=str(user.get("user_id") or "").strip(),
        action=AuditAction.LOGIN,
        resource="/api/auth/login",
        ip=_request_ip(http_request),
        details={"username": str(user.get("username") or "").strip()},
    )
    _set_access_cookie(response, token)
    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user=UserInfo(
            user_id=user["user_id"],
            username=user["username"],
            role=user.get("role") or "user",
            created_at=user.get("created_at"),
        ),
    )


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """Get current user from JWT token, or the local user when no token is present."""
    token = _token_from_request(request, credentials)
    if not token:
        return local_auth_user()

    payload = validate_access_token(token)
    if not payload:
        return local_auth_user()

    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("username"),
        "role": payload.get("role"),
        "auth_source": "token",
    }


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Return authenticated user data.

    Login is disabled for this local app. Existing bearer tokens are still
    honored when valid, but missing or stale tokens fall back to the local user
    so business endpoints remain directly usable.
    """
    token = _token_from_request(request, credentials)
    if not token:
        return local_auth_user()

    payload = validate_access_token(token)
    if not payload:
        return local_auth_user()

    user_id = str(payload.get("user_id") or "").strip()
    username = str(payload.get("username") or "").strip()
    if not user_id or not username:
        return local_auth_user()

    return {
        "user_id": user_id,
        "username": username,
        "role": payload.get("role"),
        "jti": payload.get("jti"),
        "exp": payload.get("exp"),
        "auth_source": "token",
    }


def validate_ws_token(token: str) -> Optional[dict]:
    """Validate a WebSocket auth token (from the auth cookie, or the legacy query param).

    Returns user dict or None if invalid. Falls back to local user when
    login is disabled (same behavior as require_auth).
    """
    if not token or not token.strip():
        return local_auth_user()

    payload = validate_access_token(token.strip())
    if not payload:
        return local_auth_user()

    user_id = str(payload.get("user_id") or "").strip()
    username = str(payload.get("username") or "").strip()
    if not user_id or not username:
        return local_auth_user()

    return {
        "user_id": user_id,
        "username": username,
        "role": payload.get("role"),
        "auth_source": "token",
    }


async def require_admin(user: dict = Depends(require_auth)) -> dict:
    """Require admin role."""
    if user.get("role") != "admin" or user.get("auth_source") == "local" or user.get("user_id") == "local-user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


@router.get("/me", response_model=UserInfo)
async def get_me(user: dict = Depends(require_auth)):
    """Get current user info."""
    return UserInfo(
        user_id=user["user_id"],
        username=user["username"],
        role=user["role"],
    )


@router.post("/register", response_model=UserInfo)
async def register(payload: RegisterRequest, http_request: Request, admin: dict = Depends(require_admin)):
    """Register a new user (admin only)."""
    user = create_user(payload.username, payload.password, payload.role)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    audit_logger.log(
        user_id=str((admin or {}).get("user_id") or "").strip(),
        action=AuditAction.USER_REGISTER,
        resource="/api/auth/register",
        ip=_request_ip(http_request),
        details={
            "created_user_id": str((user or {}).get("user_id") or "").strip(),
            "created_username": str((user or {}).get("username") or "").strip(),
            "created_role": str((user or {}).get("role") or "").strip(),
        },
    )

    return UserInfo(
        user_id=user["user_id"],
        username=user["username"],
        role=user["role"],
        created_at=user.get("created_at"),
    )


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    http_request: Request,
    user: dict = Depends(require_auth),
):
    """Change current user's password."""
    success = change_user_password(
        user["username"],
        payload.old_password,
        payload.new_password,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid old password",
        )
    audit_logger.log(
        user_id=str((user or {}).get("user_id") or "").strip(),
        action=AuditAction.PASSWORD_CHANGE,
        resource="/api/auth/change-password",
        ip=_request_ip(http_request),
        details={"username": str((user or {}).get("username") or "").strip()},
    )
    return {"message": "Password changed successfully"}


@router.post("/logout")
async def logout(http_request: Request, response: Response, user: dict = Depends(require_auth)) -> dict:
    """Revoke the current JWT (best-effort)."""

    _clear_access_cookie(response)
    jti = str((user or {}).get("jti") or "").strip()
    try:
        exp_ts = int((user or {}).get("exp") or 0)
    except (TypeError, ValueError):
        exp_ts = 0
    if jti:
        revoke_token_jti(jti=jti, exp_ts=exp_ts)
    audit_logger.log(
        user_id=str((user or {}).get("user_id") or "").strip(),
        action=AuditAction.LOGOUT,
        resource="/api/auth/logout",
        ip=_request_ip(http_request),
        details={"username": str((user or {}).get("username") or "").strip()},
    )
    return {"success": True}


@router.get("/users", response_model=UserListResponse)
async def list_users(admin: dict = Depends(require_admin)):
    """List all users (admin only)."""
    users = get_all_users()
    return UserListResponse(
        users=[UserInfo(**u) for u in users],
        total=len(users),
    )
