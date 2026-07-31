from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.database.paths import resolve_db_path
from backend.database.schema import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False：作为库被进程内调用时（CI/测试套件）不得
    # 关闭宿主进程既有 logger，否则后续 assertLogs 等日志断言会静默失效。
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _sync_database_url() -> str:
    configured = str(config.get_main_option("sqlalchemy.url") or "").strip()
    if configured:
        return configured.replace("sqlite+aiosqlite:///", "sqlite:///")
    return f"sqlite:///{resolve_db_path().as_posix()}"


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _sync_database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
