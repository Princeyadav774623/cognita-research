"""Research runs as a durable job, not inside the request that asked for it.

A research query takes about two minutes. It used to run inside the WebSocket
handler, so anything that ended the connection ended the research: a deploy, an
instance being recycled, a laptop lid, a refresh. The user lost the run and was
refunded, and the work already paid for at the model provider was thrown away.

Now the API only records the request. A worker (worker.py) claims it, runs the
pipeline, and writes each progress event to `research_events`. The WebSocket
reads those events back, so a client can drop, reconnect with the last event id
it saw, and carry on — or arrive late and replay the whole run.

Claiming is a lease, as in Veracity's queue: a worker sets `leased_until` into
the future and keeps pushing it out while it works. If the worker dies the lease
lapses and another worker takes the job. `FOR UPDATE SKIP LOCKED` means several
workers poll one table without ever claiming the same job. The attempt count is
the fencing token — every write a worker makes is conditional on still holding
the attempt it claimed, so a worker that lost its job cannot write over the one
that took it.

The API side goes through tenant_session (the RLS-bound role); the worker side
goes through the owner engine, because claiming has to see every tenant's jobs.
"""
import logging
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import (BigInteger, Column, DateTime, ForeignKey, Index, Integer,
                        JSON, String, text)

from db import Base, SessionLocal, tenant_session

logger = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}/{os.getpid()}"

# Long enough to ride out one slow model call, short enough that a dead
# worker's job is picked up while the user is still watching.
LEASE_SECONDS = 90
MAX_ATTEMPTS = 2
# Events are a replay buffer for reconnecting clients, not a record — the
# finished report lives in research_sessions.
KEEP_FINISHED_JOBS = timedelta(days=2)

TERMINAL_STATES = ("done", "failed", "cancelled")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchJob(Base):
    __tablename__ = "research_jobs"

    # The research session id. One id from submission to saved report, so a
    # client never has to map a job back to the session it produced.
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    query = Column(String, nullable=False)
    state = Column(String, nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=MAX_ATTEMPTS)
    run_after = Column(DateTime(timezone=True), nullable=False, default=_now)
    leased_until = Column(DateTime(timezone=True), nullable=True)
    leased_by = Column(String, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_research_jobs_claimable", "state", "run_after"),)


class ResearchEvent(Base):
    __tablename__ = "research_events"

    # Doubles as the client's resume cursor: ids only ever increase, so
    # "everything after N" is exact across reconnects.
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("research_jobs.id", ondelete="CASCADE"),
                    nullable=False)
    user_id = Column(String, nullable=False)
    attempt = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (Index("ix_research_events_job_id_id", "job_id", "id"),)


def _job_dict(job: ResearchJob) -> dict:
    return {
        "session_id": job.id,
        "query": job.query,
        "state": job.state,
        "attempts": job.attempts,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


# =============================================
# API side — tenant-scoped
# =============================================

def enqueue(user_id: str, job_id: str, query: str) -> dict:
    """Record a research request. The caller has already reserved quota."""
    with tenant_session(user_id) as db:
        job = ResearchJob(id=job_id, user_id=user_id, query=query)
        db.add(job)
        db.commit()
        return _job_dict(job)


def get_job(user_id: str, job_id: str) -> dict | None:
    with tenant_session(user_id) as db:
        job = (db.query(ResearchJob)
               .filter(ResearchJob.id == job_id, ResearchJob.user_id == user_id)
               .first())
        return _job_dict(job) if job else None


def events_after(user_id: str, job_id: str, after: int, limit: int = 500) -> list[tuple[int, dict]]:
    with tenant_session(user_id) as db:
        rows = (db.query(ResearchEvent.id, ResearchEvent.payload)
                .filter(ResearchEvent.job_id == job_id,
                        ResearchEvent.user_id == user_id,
                        ResearchEvent.id > after)
                .order_by(ResearchEvent.id)
                .limit(limit)
                .all())
        return [(r.id, r.payload) for r in rows]


def cancel(user_id: str, job_id: str) -> bool:
    """Stop a job that has not finished. True if this call is what stopped it.

    Only the state changes. A worker running it finds out at its next write,
    which the fence refuses, and stops there without writing anything.
    """
    with tenant_session(user_id) as db:
        n = (db.query(ResearchJob)
             .filter(ResearchJob.id == job_id,
                     ResearchJob.user_id == user_id,
                     ResearchJob.state.in_(("queued", "running")))
             .update({"state": "cancelled", "finished_at": _now(),
                      "leased_until": None}, synchronize_session=False))
        db.commit()
        return n == 1


def delete_user_jobs(user_id: str) -> int:
    with tenant_session(user_id) as db:
        n = (db.query(ResearchJob)
             .filter(ResearchJob.user_id == user_id)
             .delete(synchronize_session=False))
        db.commit()
        return n


# =============================================
# Worker side — owner engine, across tenants
# =============================================

class LeaseLost(RuntimeError):
    """The job was cancelled or taken by another worker. Stop; write nothing."""


@dataclass(frozen=True)
class Lease:
    """Which claim a worker is acting on. Taken at claim time and never re-read
    from the row, because the row is exactly what changes when it is lost."""
    job_id: str
    user_id: str
    query: str
    attempt: int
    max_attempts: int
    holder: str = WORKER_ID


def claim() -> Lease | None:
    """Take one runnable job: queued and due, or running on a lapsed lease
    with attempts to spare. None when there is nothing to do."""
    now = _now()
    with SessionLocal() as db:
        row = db.execute(text("""
            UPDATE research_jobs SET
                state        = 'running',
                attempts     = attempts + 1,
                leased_until = :until,
                leased_by    = :worker
            WHERE id = (
                SELECT id FROM research_jobs
                WHERE (state = 'queued' AND run_after <= :now)
                   OR (state = 'running' AND leased_until < :now
                       AND attempts < max_attempts)
                ORDER BY run_after
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, user_id, query, attempts, max_attempts
        """), {"until": now + timedelta(seconds=LEASE_SECONDS),
               "worker": WORKER_ID, "now": now}).first()
        db.commit()
    if row is None:
        return None
    return Lease(row.id, row.user_id, row.query, row.attempts, row.max_attempts)


def _fence(db, lease: Lease, values: dict) -> bool:
    """Update the job only while this lease still holds it. Does not commit."""
    n = (db.query(ResearchJob)
         .filter(ResearchJob.id == lease.job_id,
                 ResearchJob.state == "running",
                 ResearchJob.attempts == lease.attempt,
                 ResearchJob.leased_by == lease.holder)
         .update(values, synchronize_session=False))
    return n == 1


def _extended() -> dict:
    return {"leased_until": _now() + timedelta(seconds=LEASE_SECONDS)}


def _add_events(db, lease: Lease, payloads: list[dict]) -> None:
    for payload in payloads:
        db.add(ResearchEvent(job_id=lease.job_id, user_id=lease.user_id,
                             attempt=lease.attempt, payload=payload))


def append(lease: Lease, payloads: list[dict]) -> None:
    """Publish events and extend the lease in one transaction, or raise LeaseLost.

    Every write is also a heartbeat, so a job that is producing output can
    never be reclaimed out from under the worker producing it.
    """
    with SessionLocal() as db:
        if not _fence(db, lease, _extended()):
            db.rollback()
            raise LeaseLost(lease.job_id)
        _add_events(db, lease, payloads)
        db.commit()


def extend(lease: Lease) -> None:
    append(lease, [])


def complete(lease: Lease, payload: dict) -> bool:
    with SessionLocal() as db:
        if not _fence(db, lease, {"state": "done", "finished_at": _now(),
                                  "leased_until": None}):
            db.rollback()
            return False
        _add_events(db, lease, [payload])
        db.commit()
        return True


def fail(lease: Lease, error: str) -> str | None:
    """Retry if attempts remain, otherwise give up.

    Returns "retry", "failed", or None if the lease was already lost. Only
    "failed" means the caller should refund — a retry is still going to
    deliver what the user paid for.
    """
    final = lease.attempt >= lease.max_attempts
    with SessionLocal() as db:
        if final:
            values = {"state": "failed", "finished_at": _now(),
                      "leased_until": None, "error": error[:4000]}
            event = {"type": "error", "message": "Research failed. Your query has been refunded."}
        else:
            values = {"state": "queued", "leased_until": None, "leased_by": None,
                      "error": error[:4000],
                      "run_after": _now() + timedelta(seconds=5 * lease.attempt)}
            event = {"type": "restart", "message": "Hit an error — retrying from the start"}
        if not _fence(db, lease, values):
            db.rollback()
            return None
        _add_events(db, lease, [event])
        db.commit()
    return "failed" if final else "retry"


def release(lease: Lease) -> bool:
    """Hand a job back without spending an attempt — the worker is shutting
    down, and the job did nothing wrong. The next worker starts it at once
    rather than waiting out the lease."""
    with SessionLocal() as db:
        if not _fence(db, lease, {"state": "queued", "attempts": lease.attempt - 1,
                                  "leased_until": None, "leased_by": None}):
            db.rollback()
            return False
        _add_events(db, lease, [{"type": "restart",
                                 "message": "Server restarted — picking the research back up"}])
        db.commit()
        return True


def reap_exhausted() -> list[str]:
    """Fail jobs whose last permitted attempt died with its worker.

    claim() will not take them again, so without this they would sit in
    'running' forever. Returns the user ids to refund, one per job.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            UPDATE research_jobs SET state = 'failed', finished_at = :now,
                   leased_until = NULL, error = 'worker lost on final attempt'
            WHERE state = 'running' AND leased_until < :now
              AND attempts >= max_attempts
            RETURNING id, user_id, attempts
        """), {"now": _now()}).all()
        for r in rows:
            db.add(ResearchEvent(job_id=r.id, user_id=r.user_id, attempt=r.attempts,
                                 payload={"type": "error",
                                          "message": "Research failed. Your query has been refunded."}))
        db.commit()
    return [r.user_id for r in rows]


def prune() -> int:
    """Drop finished jobs (and their events) once nobody will reconnect to them."""
    with SessionLocal() as db:
        n = db.execute(text(
            "DELETE FROM research_jobs WHERE finished_at < :cutoff"
        ), {"cutoff": _now() - KEEP_FINISHED_JOBS}).rowcount
        db.commit()
    return n
