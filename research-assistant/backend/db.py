from contextlib import contextmanager
from sqlalchemy import create_engine, Column, String, Float, DateTime, JSON, text
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
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# Low-privilege runtime connection (no BYPASSRLS) — every request-serving
# query goes through this one, so Postgres RLS is real defense-in-depth on
# top of the application-layer user_id filtering, not just a checkbox.
if not settings.app_database_url:
    raise RuntimeError(
        "APP_DATABASE_URL is required — this is the low-privilege role "
        "runtime queries use so Row-Level Security actually applies. "
        "Set it in your .env (see .env.example)."
    )
app_engine = create_engine(settings.app_database_url)
AppSessionLocal = sessionmaker(bind=app_engine, autoflush=False, autocommit=False)


@contextmanager
def tenant_session(user_id: str):
    """A DB session scoped to one user: sets the Postgres session variable
    RLS policies check. Session-scoped (not transaction-local) because
    callers may commit multiple times within one tenant_session — a
    transaction-local GUC would reset after the first commit and start
    hiding the user's own just-written rows from RLS. Safe under pooling
    because every checkout re-sets this as its first statement, always
    before any query that could be affected by a stale prior value.
    (set_config is Postgres-specific — skipped under SQLite, which the test
    suite uses for isolated unit tests; RLS itself is verified against real
    Postgres separately, not through this code path.)"""
    db = AppSessionLocal()
    try:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT set_config('app.current_user_id', :uid, false)"), {"uid": user_id})
        yield db
    finally:
        db.close()


class ResearchSessionRecord(Base):
    __tablename__ = "research_sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    query = Column(String, nullable=False)
    status = Column(String, default="pending")
    final_report = Column(String, default="")
    sources = Column(JSON, default=list)
    verified_claims = Column(JSON, default=list)
    confidence = Column(Float, default=0.0)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_add_user_id()
    logger.info(f"[DB] Initialized at {DB_URL}")


def _migrate_add_user_id():
    """Idempotent column-add for existing deployments created before
    multi-tenancy was introduced. A stopgap until proper Alembic migrations
    replace create_all() entirely."""
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE research_sessions ADD COLUMN IF NOT EXISTS user_id VARCHAR"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_research_sessions_user_id ON research_sessions (user_id)"
        ))


def save_session(session_id: str, user_id: str, query: str, final_state: dict) -> None:
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
            confidence=final_state.get("overall_confidence", 0.0),
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
        "verified_claims": record.verified_claims,
        "confidence": record.confidence,
        "error": record.error,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
