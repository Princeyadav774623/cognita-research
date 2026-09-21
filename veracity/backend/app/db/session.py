"""Engines, sessions, and the tenant scoping that row-level security keys on.

Two engines on purpose. The owner runs migrations and anything with no user
context; the app role owns nothing and has no BYPASSRLS, so policies actually
bind to it. Pointing both at the same role makes every policy inert while still
logging a reassuring startup line, which is the failure mode worth designing
against.

The tenant lives in a ContextVar rather than being set once per session, and
that detail is load-bearing. Postgres session variables are bound to the
*connection*, and a commit releases the connection back to the pool. Code that
committed and then re-read the same row got a connection with the variable
cleared, and row-level security correctly hid the row it had just written.
Binding at checkout from a ContextVar means every connection taken during a
request is scoped the same way, however many transactions it spans.
"""
from __future__ import annotations

import contextlib
import contextvars
import logging

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

log = logging.getLogger("db")

TENANT_GUC = "app.current_user_id"

_current_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_tenant", default=None
)

_POOL = {
    "pool_pre_ping": True,   # a pooled connection can be dead after an idle gap
    "pool_recycle": 280,     # under the 300 s most managed proxies cut at
}

owner_engine = create_engine(settings().database_url, future=True, **_POOL)
app_engine = create_engine(settings().database_url_app, future=True, **_POOL)

OwnerSession = sessionmaker(bind=owner_engine, expire_on_commit=False,
                            future=True)
AppSession = sessionmaker(bind=app_engine, expire_on_commit=False, future=True)


@event.listens_for(app_engine, "checkout")
def _scope_connection_to_tenant(dbapi_conn, _record, _proxy):
    """Stamp the tenant onto every connection the app role hands out.

    `set_config(..., false)` is session scope rather than transaction scope, so
    it survives the commits inside a single checkout. An unset tenant writes the
    empty string, and the policies compare against a non-empty id, so an
    unscoped connection matches nothing — it fails closed rather than open.
    """
    tenant = _current_tenant.get() or ""
    with dbapi_conn.cursor() as cur:
        cur.execute("SELECT set_config(%s, %s, false)", (TENANT_GUC, tenant))


@contextlib.contextmanager
def tenant(user_id: str):
    """Scope everything inside the block to `user_id`."""
    if not user_id:
        raise ValueError("a tenant id is required; '' disables every policy")
    token = _current_tenant.set(user_id)
    try:
        yield
    finally:
        _current_tenant.reset(token)


def current_tenant() -> str | None:
    return _current_tenant.get()


@contextlib.contextmanager
def app_session(user_id: str) -> Session:
    """A session as the low-privilege role, scoped to one user."""
    with tenant(user_id):
        session = AppSession()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


@contextlib.contextmanager
def owner_session() -> Session:
    """A session as the owner. Bypasses row-level security — use sparingly.

    Legitimate callers: migrations, the job worker claiming work across tenants,
    and anything else with no user to scope to. Everything serving a request
    should use `app_session`.
    """
    session = OwnerSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping() -> None:
    """Fail fast at startup rather than on the first request."""
    for name, engine in (("owner", owner_engine), ("app", app_engine)):
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log.info("[DB] %s connection ok", name)
