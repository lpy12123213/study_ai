"""Authentication request/response schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class UserInfo(BaseModel):
    """User information."""

    user_id: str
    username: str
    role: str
    created_at: Optional[str] = None


class RegisterRequest(BaseModel):
    """User registration request."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    role: str = Field(default="user")


class ChangePasswordRequest(BaseModel):
    """Change password request."""

    old_password: str
    new_password: str = Field(..., min_length=6)


class UserListResponse(BaseModel):
    """Response for user list (admin only)."""

    users: list[UserInfo]
    total: int
