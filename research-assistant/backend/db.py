import contextvars
import os
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
from sqlalchemy import create_engine, event, inspect, Column, String, Float, Integer, DateTime, JSON, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone
from config import get_settings
import logging

logger = logging.getLogger(__name__)
settings = get_settings()

if not settings.database_url:
    raise RuntimeError(
        "DATABASE_URL is required — SQLite is not supported. "
        "Multi-instance deployments and pgvector both require real Postgres. "
        "Set DATABASE_URL in your .env (see .env.example)."
    )
DB_URL = settings.database_url

# Owner/admin connection — used ONLY for schema migrations at startup.
# It has BYPASSRLS, so it must never be used to serve a real request.
# Managed Postgres drops idle connections; without pre-ping the first request
# after a quiet period fails instead of reconnecting. recycle stays under the
# common 300s idle timeout.
_POOL = {"pool_pre_ping": True, "pool_recycle": 280}

engine = create_engine(DB_URL, **_POOL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# Low-privilege runtime connection (no BYPASSRLS) — every request-serving
# query goes through this one, so Postgres RLS is real defense-in-depth on
# top of the application-layer user_id filtering, not just a checkbox.
#
# The policies themselves live in rls.py and are applied at startup. They only
# bite when this role is NOT the table owner: RLS is enabled but not forced, so
# that the owner engine above can still run migrations and the Stripe webhook
# path, which has no user JWT and must read across tenants. If both URLs name
# the same role, rls.apply_rls_policies() logs a warning saying so.
if not settings.app_database_url:
    raise RuntimeError(
        "APP_DATABASE_URL is required — this is the low-privilege role "
        "runtime queries use so Row-Level Security actually applies. "
        "Set it in your .env (see .env.example)."
    )
app_engine = create_engine(settings.app_database_url, **_POOL)
AppSessionLocal = sessionmaker(bind=app_engine, autoflush=False, autocommit=False)


# Which tenant the current call stack is acting for. A ContextVar rather than
# a plain global because concurrent requests each need their own, and it
# propagates correctly across asyncio tasks.
_current_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_tenant", default=None
)


@event.listens_for(app_engine, "checkout")
def _scope_connection_to_tenant(dbapi_conn, _record, _proxy):
    """Bind every pooled connection to the tenant of whoever checked it out.

    Setting the GUC once inside tenant_session is not enough. SQLAlchemy
    releases the connection back to the pool on commit and checks another one
    out for the next statement, so a session that commits and then reads —
    consume_quota does exactly this — continued on a connection carrying either
    nothing or, worse, the previous tenant's id.

    Doing it here means a connection cannot be handed out in the wrong scope:
    there is no window between checkout and the first query. With no tenant set
    the value is blank, so RLS shows nothing and an unscoped session fails
    closed.
    """
    if not dbapi_conn.__class__.__module__.startswith("psycopg2"):
        return
    with dbapi_conn.cursor() as cur:
        cur.execute("SELECT set_config('app.current_user_id', %s, false)",
                    (_current_tenant.get() or "",))
    dbapi_conn.commit()


def _safe_url(url: str) -> str:
    """Strip the password out of a connection string before it is logged.

    DATABASE_URL carries the Postgres password inline. Logging it verbatim puts
    a live credential into stdout, log files, and whatever aggregator collects
    them in production — where it long outlives any password rotation.
    """
    try:
        parsed = urlsplit(url)
        if parsed.password:
            host = parsed.hostname or ""
            if parsed.port:
                host = f"{host}:{parsed.port}"
            netloc = f"{parsed.username}:***@{host}" if parsed.username else f"***@{host}"
            return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except Exception:
        pass
    return url


@contextmanager
def tenant_session(user_id: str):
    """A DB session scoped to one user.

    The tenant is published to the ContextVar above, and the pool's checkout
    listener stamps it onto every connection this session touches — including
    the ones it picks up after a commit. That is what makes RLS hold across a
    read-modify-commit-read sequence.

    (Postgres-specific; skipped under SQLite, which the unit tests use. RLS
    itself is verified against real Postgres by scripts/verify_rls.py.)
    """
    token = _current_tenant.set(user_id)
    db = AppSessionLocal()
    try:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT set_config('app.current_user_id', :uid, false)"), {"uid": user_id})
        yield db
    finally:
        db.close()
        _current_tenant.reset(token)


class ResearchSessionRecord(Base):
    __tablename__ = "research_sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    query = Column(String, nullable=False)
    status = Column(String, default="pending")
    final_report = Column(String, default="")
    sources = Column(JSON, default=list)
    images = Column(JSON, default=list)
    verified_claims = Column(JSON, default=list)
    confidence = Column(Float, default=0.0)
    # Measured token usage and the estimated spend derived from it. Stored per
    # session because "what does a deep research run cost?" is a question about
    # the distribution across real runs, not about one log line.
    total_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(Float, default=0.0)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def _alembic_config():
    from alembic.config import Config
    cfg = Config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "alembic.ini"))
    cfg.set_main_option("script_location",
                        os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations"))
    cfg.set_main_option("sqlalchemy.url", DB_URL)
    # Tells env.py it is running inside the app, not the CLI, so it leaves the
    # application's logging configuration alone.
    cfg.attributes["embedded"] = True
    return cfg


def init_db():
    """Bring the schema up to date.

    Replaces create_all() plus a growing pile of hand-written
    ADD COLUMN IF NOT EXISTS statements: those could add columns but never
    change or remove one, and nothing recorded which had been applied.

    A database that predates Alembic has the tables but no alembic_version, so
    running upgrade head would try to create what is already there. It is
    stamped instead — adopting the existing schema as the baseline — and only
    later migrations run against it.
    """
    from alembic import command
    from alembic.runtime.migration import MigrationContext

    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    with engine.connect() as conn:
        has_version = MigrationContext.configure(conn).get_current_revision() is not None
        pre_alembic = inspect(engine).has_table("research_sessions")

    cfg = _alembic_config()
    if pre_alembic and not has_version:
        logger.info("[DB] Existing schema found with no migration history — stamping baseline")
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")

    logger.info(f"[DB] Initialized at {_safe_url(DB_URL)}")


def save_session(session_id: str, user_id: str, query: str, final_state: dict) -> None:
    cost = final_state.get("cost_tracking") or {}
    with tenant_session(user_id) as db:
        record = ResearchSessionRecord(
            id=session_id,
            user_id=user_id,
            query=query,
            status="error" if final_state.get("error") else "complete",
            final_report=final_state.get("final_report", ""),
            sources=[
                {"title": d["title"], "url": d["url"]}
                for d in final_state.get("source_documents", [])
            ],
            verified_claims=final_state.get("verified_claims", []),
            images=final_state.get("images", [])[:12],
            confidence=final_state.get("overall_confidence", 0.0),
            total_tokens=int(cost.get("total_tokens", 0)),
            estimated_cost_usd=float(cost.get("estimated_cost_usd", 0.0)),
            error=final_state.get("error"),
        )
        db.merge(record)
        db.commit()


def get_session(session_id: str, user_id: str) -> dict | None:
    with tenant_session(user_id) as db:
        record = (
            db.query(ResearchSessionRecord)
            .filter(ResearchSessionRecord.id == session_id, ResearchSessionRecord.user_id == user_id)
            .first()
        )
        return _to_dict(record) if record else None


def list_sessions(user_id: str, limit: int = 50) -> list[dict]:
    with tenant_session(user_id) as db:
        records = (
            db.query(ResearchSessionRecord)
            .filter(ResearchSessionRecord.user_id == user_id)
            .order_by(ResearchSessionRecord.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_dict(r) for r in records]


def delete_session(session_id: str, user_id: str) -> bool:
    with tenant_session(user_id) as db:
        record = (
            db.query(ResearchSessionRecord)
            .filter(ResearchSessionRecord.id == session_id, ResearchSessionRecord.user_id == user_id)
            .first()
        )
        if not record:
            return False
        db.delete(record)
        db.commit()
        return True


def delete_user_data(user_id: str) -> int:
    """Delete all research sessions and history belonging to user (GDPR/Account Purge)."""
    with tenant_session(user_id) as db:
        deleted_count = (
            db.query(ResearchSessionRecord)
            .filter(ResearchSessionRecord.user_id == user_id)
            .delete(synchronize_session=False)
        )
        db.commit()
        return deleted_count


def _to_dict(record: ResearchSessionRecord) -> dict:
    return {
        "session_id": record.id,
        "query": record.query,
        "status": record.status,
        "final_report": record.final_report,
        "sources": record.sources,
        "images": record.images or [],
        "verified_claims": record.verified_claims,
        "confidence": record.confidence,
        "total_tokens": record.total_tokens,
        "estimated_cost_usd": record.estimated_cost_usd,
        "error": record.error,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
