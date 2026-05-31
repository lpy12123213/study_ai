"""Cross-domain security primitives.

This package centralizes low-level security helpers (password hashing, token
verification helpers, ...) that must keep a single canonical implementation
across the codebase. Domain modules should import from here rather than
re-implementing bcrypt parameters or JWT helpers.
"""

from backend.core.security.password import (
    hash_password,
    verify_password,
)

__all__ = [
    "hash_password",
    "verify_password",
]
