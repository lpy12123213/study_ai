"""Centralized error messages for API responses."""

from __future__ import annotations

# Authentication errors
AUTH_INVALID_CREDENTIALS = "Invalid username or password"
AUTH_TOKEN_EXPIRED = "Token has expired"
AUTH_TOKEN_INVALID = "Invalid token"
AUTH_NOT_AUTHENTICATED = "Not authenticated"
AUTH_ADMIN_REQUIRED = "Admin access required"
AUTH_USERNAME_EXISTS = "Username already exists"
AUTH_INVALID_OLD_PASSWORD = "Invalid old password"

# Resource errors
RESOURCE_NOT_FOUND = "Resource not found"
PAPER_NOT_FOUND = "Paper not found"
CONVERSATION_NOT_FOUND = "Conversation not found"
QUESTION_NOT_FOUND = "Question not found"

# Validation errors
VALIDATION_REQUIRED_FIELD = "This field is required"
VALIDATION_INVALID_FORMAT = "Invalid format"
VALIDATION_TOO_LONG = "Value is too long"
VALIDATION_TOO_SHORT = "Value is too short"

# Server errors
SERVER_INTERNAL_ERROR = "Internal server error"
SERVER_SERVICE_UNAVAILABLE = "Service temporarily unavailable"
SERVER_TIMEOUT = "Request timed out"

# Crawler errors
CRAWLER_LOGIN_REQUIRED = "Login required for this operation"
CRAWLER_RATE_LIMITED = "Rate limited, please try again later"
CRAWLER_PARSE_ERROR = "Failed to parse response"

# Lesson plan errors
LESSON_PLAN_NOT_FOUND = "Lesson plan not found"
LESSON_PLAN_GENERATION_FAILED = "Failed to generate lesson plan"
LESSON_PLAN_EXPORT_FAILED = "Failed to export lesson plan"
