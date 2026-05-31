"""Sync (sqlite-on-disk) helpers for auth user + JWT revocation persistence.

The async engine in ``backend.database.engine`` is the canonical entry point
for everything else, but ``backend.core.auth`` is called from sync paths
(FastAPI dependencies that are already inside an async context, plus a number
of unit tests that operate on the module directly). Spinning up an event loop
from those sync call sites breaks under uvicorn.

To keep the surface backwards compatible we open a short-lived ``sqlite3``
connection backed by the same DB file that the async engine uses. SQLite's
WAL mode handles the read/write interleaving with the async engine safely,
and the volume here (auth ops per request) is tiny.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from backend.core.logging_utils import get_logger
from backend.database.paths import resolve_db_path

logger = get_logger(__name__)

_conn_lock = threading.RLock()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _now_ts() -> int:
    return int(time.time())


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the auth tables if they don't exist yet.

    We can't depend on ``init_db()`` having run before the first call: the
    auth module is imported eagerly (via ``backend.app``) and ``init_db()``
    runs in the FastAPI lifespan. Idempotent ``CREATE TABLE IF NOT EXISTS``
    keeps things working in either order, including in unit tests that import
    the module directly.
    """

    conn.execute(
        "CREATE TABLE IF NOT EXISTS auth_users ("
        "user_id VARCHAR(64) PRIMARY KEY,"
        "username VARCHAR(120) NOT NULL UNIQUE,"
        "password_hash VARCHAR(200) NOT NULL DEFAULT '',"
        "role VARCHAR(32) NOT NULL DEFAULT 'user',"
        "token_version INTEGER NOT NULL DEFAULT 1,"
        "created_at DATETIME,"
        "updated_at DATETIME"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_auth_users_username ON auth_users (username)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS auth_revoked_jwt ("
        "jti VARCHAR(64) PRIMARY KEY,"
        "exp_ts INTEGER NOT NULL DEFAULT 0,"
        "revoked_at DATETIME"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_auth_revoked_jwt_exp_ts ON auth_revoked_jwt (exp_ts)")


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """Open a short-lived sqlite connection.

    Each call opens its own connection so the helpers stay thread-safe under
    uvicorn's worker pool. ``timeout`` lets us wait briefly when another
    connection holds the write lock (the async engine writes infrequently).
    """

    db_path: Path = resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None, check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        _ensure_tables(conn)
        yield conn
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            logger.debug("auth_users_conn_close_failed", exc_info=True)


def _row_to_user(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "user_id": str(row["user_id"] or ""),
        "username": str(row["username"] or ""),
        "password_hash": str(row["password_hash"] or ""),
        "role": str(row["role"] or "user"),
        "token_version": int(row["token_version"] or 1),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    uname = str(username or "").strip()
    if not uname:
        return None
    with _connection() as conn:
        cur = conn.execute(
            "SELECT user_id, username, password_hash, role, token_version, created_at, updated_at "
            "FROM auth_users WHERE username = ? LIMIT 1",
            (uname,),
        )
        row = cur.fetchone()
        return _row_to_user(row) if row else None


def list_users() -> List[Dict[str, Any]]:
    with _connection() as conn:
        cur = conn.execute(
            "SELECT user_id, username, password_hash, role, token_version, created_at, updated_at "
            "FROM auth_users ORDER BY created_at ASC"
        )
        return [_row_to_user(row) for row in cur.fetchall()]


def insert_user(*, user_id: str, username: str, password_hash: str, role: str, token_version: int = 1) -> bool:
    """Insert a new user. Returns ``False`` when the username is already taken."""

    uname = str(username or "").strip()
    uid = str(user_id or "").strip()
    if not uname or not uid:
        return False
    now = _utcnow_iso()
    try:
        with _conn_lock, _connection() as conn:
            conn.execute(
                "INSERT INTO auth_users "
                "(user_id, username, password_hash, role, token_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, uname, str(password_hash or ""), str(role or "user"), int(token_version or 1), now, now),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def update_password_and_bump_version(*, username: str, password_hash: str) -> Tuple[bool, int]:
    """Set ``password_hash`` and increment ``token_version`` atomically.

    Returns ``(success, new_token_version)``.
    """

    uname = str(username or "").strip()
    if not uname:
        return False, 0
    now = _utcnow_iso()
    with _conn_lock, _connection() as conn:
        cur = conn.execute(
            "UPDATE auth_users "
            "SET password_hash = ?, token_version = token_version + 1, updated_at = ? "
            "WHERE username = ?",
            (str(password_hash or ""), now, uname),
        )
        if cur.rowcount <= 0:
            return False, 0
        cur2 = conn.execute(
            "SELECT token_version FROM auth_users WHERE username = ? LIMIT 1",
            (uname,),
        )
        row = cur2.fetchone()
        return True, int((row["token_version"] if row else 0) or 0)


def upgrade_password_hash(*, username: str, password_hash: str) -> None:
    """Upgrade a legacy hash without rotating ``token_version``."""

    uname = str(username or "").strip()
    if not uname:
        return
    now = _utcnow_iso()
    with _conn_lock, _connection() as conn:
        conn.execute(
            "UPDATE auth_users SET password_hash = ?, updated_at = ? WHERE username = ?",
            (str(password_hash or ""), now, uname),
        )


def ensure_admin_row(
    *,
    user_id: str,
    username: str,
    password_hash: str,
    role: str = "admin",
    force_password_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Idempotent bootstrap of the admin user.

    - If no row matches ``username``, insert one.
    - If a row exists and ``force_password_hash`` is provided, replace the
      hash (used when ``ADMIN_PASSWORD_HASH`` is set explicitly).
    - Otherwise leave existing credentials untouched so user-changed passwords
      survive restarts.
    """

    existing = get_user_by_username(username)
    if existing is None:
        insert_user(
            user_id=str(user_id or "").strip() or "1",
            username=username,
            password_hash=password_hash,
            role=role,
            token_version=1,
        )
        return get_user_by_username(username) or {}

    if force_password_hash:
        with _conn_lock, _connection() as conn:
            conn.execute(
                "UPDATE auth_users SET password_hash = ?, updated_at = ? WHERE username = ?",
                (force_password_hash, _utcnow_iso(), username),
            )
        return get_user_by_username(username) or existing
    return existing


# --------------------------------------------------------------------------- #
# JWT revocation                                                                #
# --------------------------------------------------------------------------- #


def revoke_jti(jti: str, exp_ts: int) -> None:
    tid = str(jti or "").strip()
    if not tid:
        return
    safe_exp = int(exp_ts or 0) if int(exp_ts or 0) > 0 else _now_ts() + 24 * 3600
    now = _utcnow_iso()
    with _conn_lock, _connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO auth_revoked_jwt (jti, exp_ts, revoked_at) VALUES (?, ?, ?)",
            (tid, safe_exp, now),
        )
        # Best-effort prune of expired revocations to avoid unbounded growth.
        conn.execute("DELETE FROM auth_revoked_jwt WHERE exp_ts <= ?", (_now_ts(),))


def is_jti_revoked(jti: str) -> bool:
    tid = str(jti or "").strip()
    if not tid:
        return False
    with _connection() as conn:
        cur = conn.execute(
            "SELECT exp_ts FROM auth_revoked_jwt WHERE jti = ? LIMIT 1",
            (tid,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        try:
            exp = int(row["exp_ts"] or 0)
        except (TypeError, ValueError):
            return False
        return exp > _now_ts()


def prune_revoked_jti() -> int:
    """Remove rows whose ``exp_ts`` is in the past. Returns the deletion count."""

    with _conn_lock, _connection() as conn:
        cur = conn.execute("DELETE FROM auth_revoked_jwt WHERE exp_ts <= ?", (_now_ts(),))
        return int(cur.rowcount or 0)
