"""Single canonical password hashing helpers.

Every backend module that needs to hash or verify a password (user auth,
share-link gates, ...) MUST import from here. Re-implementing bcrypt parameters
elsewhere caused subtle drift in the past (different ``rounds`` between
``share_links`` and ``auth``) — keep this file as the only place that talks to
``bcrypt``.

Passwords are stored as bcrypt strings. Empty/None inputs hash to the empty
string, which ``verify_password`` accepts only against the empty string. This
mirrors the legacy contract used by share-link endpoints (no password = open
link).
"""

from __future__ import annotations

import bcrypt

DEFAULT_ROUNDS = 12


def hash_password(password: str, *, rounds: int = DEFAULT_ROUNDS) -> str:
    """Return a bcrypt hash of ``password`` using ``rounds`` cost.

    ``rounds`` is clamped to the bcrypt-supported range (4-31) to avoid runtime
    errors if a caller mis-configures the parameter via env. Empty or None
    inputs return an empty string so callers can distinguish ``no password``
    from a real hash.
    """

    raw = str(password or "")
    if not raw:
        return ""
    safe_rounds = max(4, min(int(rounds or DEFAULT_ROUNDS), 31))
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(rounds=safe_rounds)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verification of ``password`` against ``password_hash``.

    Returns ``True`` when:
    - ``password_hash`` is a bcrypt string and matches ``password``;
    - both ``password`` and ``password_hash`` are empty (open share-link case).
    Any malformed hash returns ``False`` rather than raising.
    """

    raw = str(password or "")
    hashed = str(password_hash or "")
    if not hashed:
        return raw == ""
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (TypeError, ValueError):
        return False
