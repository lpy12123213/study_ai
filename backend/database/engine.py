from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.core.logging_utils import get_logger
from backend.database.legacy_migrations import sync_migrate_db_schema
from backend.database.paths import resolve_db_path
from backend.database.schema import Base

logger = get_logger(__name__)

DB_PATH = resolve_db_path()
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

async_session_maker = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Initialize DB schema (create tables + best-effort migrations)."""

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(sync_migrate_db_schema)

    logger.info("db_initialized", extra={"db_path": str(DB_PATH)})


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
