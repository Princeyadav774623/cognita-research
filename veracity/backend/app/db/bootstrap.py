"""Bring a database to the current schema.

Migrations, not `create_all`. The difference matters the first time a column has
to change rather than appear: `create_all` can add a table it has never seen and
nothing else, it records nothing about what was applied, and it silently leaves
a database that is half a version behind looking identical to one that is
current.

A database that predates Alembic is *stamped* at the baseline rather than
migrated onto it. Running the initial migration against tables that already
exist fails on the first CREATE TABLE, and the obvious workaround — dropping
first — destroys the data it was meant to preserve.
"""
from __future__ import annotations

import logging
import os

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.db import rls
from app.db.session import owner_engine, ping

log = logging.getLogger("db")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _alembic_config() -> Config:
    cfg = Config(os.path.join(_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_ROOT, "migrations"))
    cfg.set_main_option("sqlalchemy.url", str(owner_engine.url))
    return cfg


def _current_revision() -> str | None:
    with owner_engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def _head_revision(cfg: Config) -> str | None:
    return ScriptDirectory.from_config(cfg).get_current_head()


def migrate() -> None:
    cfg = _alembic_config()
    current = _current_revision()
    head = _head_revision(cfg)

    if current is None:
        inspector = inspect(owner_engine)
        existing = set(inspector.get_table_names())
        if "media_items" in existing:
            # The schema is already here, from before migrations existed.
            # Upgrading would try to create tables that are present; stamping
            # records where we are without touching a row.
            base = ScriptDirectory.from_config(cfg).get_base()
            log.warning(
                "[DB] tables exist with no alembic_version — stamping at %s. "
                "Verify the schema matches the baseline before the next "
                "migration.", base,
            )
            command.stamp(cfg, base)
            current = base

    if current == head:
        log.info("[DB] schema at head (%s)", head)
        return

    log.info("[DB] migrating %s -> %s", current or "empty", head)
    command.upgrade(cfg, "head")


# Indexes that cannot be expressed in model metadata, and which alembic
# therefore proposes dropping on every autogenerate. Asserted at startup so a
# migration that removed them is caught by the next deploy rather than by a
# gradual slowdown nobody attributes to anything.
_REQUIRED_INDEXES = {
    "ix_chunks_embedding_hnsw": (
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON transcript_chunks USING hnsw (embedding vector_cosine_ops)"
    ),
    "ix_chunks_text_fts": (
        "CREATE INDEX IF NOT EXISTS ix_chunks_text_fts "
        "ON transcript_chunks USING gin (to_tsvector('english', text))"
    ),
}


def ensure_indexes() -> None:
    """Recreate the raw-SQL indexes if anything removed them."""
    with owner_engine.begin() as conn:
        present = {r[0] for r in conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'transcript_chunks'"
        ))}
        for name, ddl in _REQUIRED_INDEXES.items():
            if name not in present:
                log.warning("[DB] %s is missing — recreating. Retrieval would "
                            "otherwise run as a sequential scan.", name)
                conn.execute(text(ddl))


def init(*, run_migrations: bool = True) -> None:
    ping()
    with owner_engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    if run_migrations:
        migrate()
    ensure_indexes()
    rls.install()
    for problem in rls.verify():
        log.error("[RLS] %s", problem)
