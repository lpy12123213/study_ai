"""Authentication API endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
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

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


def _request_ip(req: Request) -> str:
    return str(getattr(req.client, "host", "") or "").strip()


def local_auth_user() -> dict:
    """Return the built-in local user used when login is disabled."""

    return {
        "user_id": "local-user",
        "username": "本地用户",
        "role": "admin",
    }


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, http_request: Request) -> LoginResponse:
    """Authenticate a user and return a JWT."""

    user = authenticate_user(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """Get current user from JWT token, or the local user when no token is present."""
    if not credentials:
        return local_auth_user()

    payload = validate_access_token(credentials.credentials)
    if not payload:
        return local_auth_user()

    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("username"),
        "role": payload.get("role"),
    }


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Return authenticated user data.

    Login is disabled for this local app. Existing bearer tokens are still
    honored when valid, but missing or stale tokens fall back to the local user
    so business endpoints remain directly usable.
    """
    if not credentials:
        return local_auth_user()

    payload = validate_access_token(credentials.credentials)
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
    }


async def require_admin(user: dict = Depends(require_auth)) -> dict:
    """Require admin role."""
    if user.get("role") != "admin":
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
async def logout(http_request: Request, user: dict = Depends(require_auth)) -> dict:
    """Revoke the current JWT (best-effort)."""

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
