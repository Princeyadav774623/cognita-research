"""Alembic environment.

The URL and metadata come from the application, not alembic.ini, so there is
one definition of each. Migrations run as the owner role (DATABASE_URL);
APP_DATABASE_URL is the low-privilege runtime role and must never own schema.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings  # noqa: E402
from db import Base  # noqa: E402
import billing  # noqa: E402,F401  — registers user_subscriptions on Base
import rag.store  # noqa: E402,F401  — registers the rag_* tables

config = context.config
# Only configure logging for the Alembic CLI. init_db() runs migrations inside
# the running app, and fileConfig defaults to disable_existing_loggers=True —
# which silenced every application logger created before it, so the server
# produced no output at all after startup.
if config.config_file_name is not None and not config.attributes.get("embedded"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # rag_chunks.embedding is a vector column, so the type has to exist
        # before any migration that references it runs.
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
