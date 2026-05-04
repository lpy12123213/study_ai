from __future__ import annotations

import os
import sqlite3
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.core.logging_utils import get_logger
from backend.database.migrations import sync_migrate_db_schema
from backend.database.paths import resolve_db_path
from backend.database.schema import Base

logger = get_logger(__name__)

DB_PATH = resolve_db_path()
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"


def _get_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


DB_BUSY_TIMEOUT_S = float(_get_float("DB_BUSY_TIMEOUT_S", 30.0))
# SQLite/aiosqlite still serializes writes at the database-file level. These pool
# knobs only control how many async connections can wait on SQLite locks; they do
# not increase write throughput like PostgreSQL. See docs/DB_CONCURRENCY.md.
DB_POOL_SIZE = int(_get_int("DB_POOL_SIZE", 5))
DB_MAX_OVERFLOW = int(_get_int("DB_MAX_OVERFLOW", 10))
DB_POOL_TIMEOUT_S = float(_get_float("DB_POOL_TIMEOUT_S", 30.0))

DB_BUSY_TIMEOUT_S = max(1.0, min(DB_BUSY_TIMEOUT_S, 300.0))
DB_POOL_SIZE = max(1, min(DB_POOL_SIZE, 50))
DB_MAX_OVERFLOW = max(0, min(DB_MAX_OVERFLOW, 200))
DB_POOL_TIMEOUT_S = max(1.0, min(DB_POOL_TIMEOUT_S, 300.0))


def sqlite_pragmas() -> tuple[str, ...]:
    """SQLite connection tuning used by both connect hooks and init checks."""

    return (
        "PRAGMA journal_mode=WAL;",
        f"PRAGMA busy_timeout={int(DB_BUSY_TIMEOUT_S * 1000)};",
        "PRAGMA foreign_keys=ON;",
        "PRAGMA synchronous=NORMAL;",
        "PRAGMA temp_store=MEMORY;",
        "PRAGMA cache_size=-32000;",
        "PRAGMA mmap_size=268435456;",
    )

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT_S,
    pool_pre_ping=True,
    connect_args={
        # sqlite3 busy timeout (seconds)
        "timeout": DB_BUSY_TIMEOUT_S,
        # allow cross-thread usage (aiosqlite uses a worker thread internally)
        "check_same_thread": False,
    },
)


@event.listens_for(engine.sync_engine, "connect")
def _on_sqlite_connect(dbapi_connection, _connection_record) -> None:  # pragma: no cover
    # Best-effort: configure SQLite for better concurrency and predictable behavior.
    try:
        cursor = dbapi_connection.cursor()
        for pragma in sqlite_pragmas():
            cursor.execute(pragma)
        cursor.close()
    except (AttributeError, RuntimeError, sqlite3.Error):
        # Never fail engine creation due to PRAGMA issues.
        logger.debug("sqlite_pragma_setup_failed", exc_info=True)


async_session_maker = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Initialize DB schema (create tables + best-effort migrations)."""

    async with engine.begin() as conn:
        # Ensure PRAGMAs are applied at least once even if connect events are skipped.
        try:
            for pragma in sqlite_pragmas():
                await conn.exec_driver_sql(pragma)
        except SQLAlchemyError:
            logger.debug("sqlite_pragma_setup_failed", exc_info=True)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(sync_migrate_db_schema)

    logger.info("db_initialized", extra={"db_path": str(DB_PATH)})


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


def pool_metrics() -> dict:
    """Expose basic pool metrics for `/api/system/*` health endpoints."""

    pool = getattr(engine, "pool", None)
    if pool is None:
        return {"pool": None}
    out = {"pool_class": type(pool).__name__}
    for name in ("size", "checkedin", "checkedout", "overflow"):
        fn = getattr(pool, name, None)
        if not callable(fn):
            continue
        try:
            out[name] = fn()
        except (RuntimeError, TypeError, ValueError):
            continue
    try:
        out["status"] = pool.status()  # type: ignore[no-untyped-call]
    except Exception:
        logger.warning("db_pool_status_probe_failed", exc_info=True)
    return out
