"""Authentication API endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.api.auth_schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserInfo,
    UserListResponse,
)
from backend.auth import (
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


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """Get current user from JWT token."""
    if not credentials:
        return None

    payload = validate_access_token(credentials.credentials)
    if not payload:
        return None

    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("username"),
        "role": payload.get("role"),
    }


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Require authentication."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    payload = validate_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = str(payload.get("user_id") or "").strip()
    username = str(payload.get("username") or "").strip()
    if not user_id or not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

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


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Login and get access token."""
    user = authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token_version = 1
    try:
        token_version = int(user.get("token_version") or 1)
    except Exception:
        token_version = 1

    token = create_access_token(
        {
            "user_id": user["user_id"],
            "username": user["username"],
            "role": user["role"],
            "ver": token_version,
        }
    )

    return LoginResponse(
        access_token=token,
        user_id=user["user_id"],
        username=user["username"],
        role=user["role"],
    )


@router.get("/me", response_model=UserInfo)
async def get_me(user: dict = Depends(require_auth)):
    """Get current user info."""
    return UserInfo(
        user_id=user["user_id"],
        username=user["username"],
        role=user["role"],
    )


@router.post("/register", response_model=UserInfo)
async def register(request: RegisterRequest, admin: dict = Depends(require_admin)):
    """Register a new user (admin only)."""
    user = create_user(request.username, request.password, request.role)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    return UserInfo(
        user_id=user["user_id"],
        username=user["username"],
        role=user["role"],
        created_at=user.get("created_at"),
    )


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    user: dict = Depends(require_auth),
):
    """Change current user's password."""
    success = change_user_password(
        user["username"],
        request.old_password,
        request.new_password,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid old password",
        )
    return {"message": "Password changed successfully"}


@router.post("/logout")
async def logout(user: dict = Depends(require_auth)) -> dict:
    """Revoke the current JWT (best-effort)."""

    jti = str((user or {}).get("jti") or "").strip()
    try:
        exp_ts = int((user or {}).get("exp") or 0)
    except Exception:
        exp_ts = 0
    if jti:
        revoke_token_jti(jti=jti, exp_ts=exp_ts)
    return {"success": True}


@router.get("/users", response_model=UserListResponse)
async def list_users(admin: dict = Depends(require_admin)):
    """List all users (admin only)."""
    users = get_all_users()
    return UserListResponse(
        users=[UserInfo(**u) for u in users],
        total=len(users),
    )
