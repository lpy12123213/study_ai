"""Authentication API endpoints."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.auth import (
    authenticate_user,
    create_access_token,
    decode_token,
    create_user,
    get_all_users,
    change_user_password,
)
from backend.api.auth_schemas import (
    LoginRequest,
    LoginResponse,
    UserInfo,
    RegisterRequest,
    ChangePasswordRequest,
    UserListResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """Get current user from JWT token."""
    if not credentials:
        return None
    
    payload = decode_token(credentials.credentials)
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
    
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    
    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("username"),
        "role": payload.get("role"),
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
    
    token = create_access_token({
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
    })
    
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


@router.get("/users", response_model=UserListResponse)
async def list_users(admin: dict = Depends(require_admin)):
    """List all users (admin only)."""
    users = get_all_users()
    return UserListResponse(
        users=[UserInfo(**u) for u in users],
        total=len(users),
    )
