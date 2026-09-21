"""Alembic environment.

Migrations run as the OWNER, never the application role. The application role
deliberately owns nothing and cannot bypass row-level security; handing it DDL
would defeat the point of having two roles at all.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import Base  # noqa: E402

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

url = os.getenv("DATABASE_URL")
if not url:
    raise RuntimeError("DATABASE_URL is not set; migrations run as the owner")
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata

# Indexes created in raw SQL because they cannot be expressed in model
# metadata: an HNSW index with an operator class, and an expression index over
# to_tsvector(). Alembic compares the database against the models, does not find
# them there, and proposes dropping them on every single autogenerate. Left to
# itself it would eventually get one past review, and the symptom would be
# retrieval quietly falling back to a sequential scan — slower, never wrong, and
# attributed to anything but this.
_RAW_SQL_INDEXES = {"ix_chunks_embedding_hnsw", "ix_chunks_text_fts"}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "index" and name in _RAW_SQL_INDEXES:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata,
                      literal_binds=True, compare_type=True,
                      compare_server_default=True,
                      include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True, compare_server_default=True,
                          include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
