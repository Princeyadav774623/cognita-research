"""Create the schema and install policies.

Alembic owns migrations from the first release; this is what gets a fresh
database to a working state before there is anything to migrate from. The order
matters: the vector extension has to exist before any table declaring a
`vector` column, or creation fails with `type "vector" does not exist` — an
error that only ever appears on a first install and therefore never in
development.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db import rls
from app.db.models import Base
from app.db.session import owner_engine, ping

log = logging.getLogger("db")


def init() -> None:
    ping()
    with owner_engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(owner_engine)
    log.info("[DB] schema ready")
    rls.install()
    problems = rls.verify()
    for p in problems:
        log.error("[RLS] %s", p)
