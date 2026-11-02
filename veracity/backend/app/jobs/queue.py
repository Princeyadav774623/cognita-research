"""A durable job queue, in Postgres.

Cognita runs ingestion inside the web process. A restart mid-upload strands the
row in `processing` forever, and the mitigation is a reaper that fails it after
fifteen minutes — its own report calls that "a mitigation, not a fix". Media
work is minutes long rather than seconds, so the same design here would strand
jobs routinely rather than occasionally.

The fix is a lease. A worker claims a job by setting `leased_until` into the
future; if it dies, the lease expires and the next worker to poll picks the job
up and retries it. Nothing is lost by a restart, and no separate broker has to
be operated, backed up or reasoned about — the queue is in the same transaction
as the rows the job is about.

`FOR UPDATE SKIP LOCKED` is what makes that safe under concurrency: each worker
locks the row it claims and skips rows another worker already holds, so N
workers poll the same table without ever handing out the same job twice.
"""
from __future__ import annotations

import logging
import socket
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Job

log = logging.getLogger("jobs")

WORKER_ID = f"{socket.gethostname()}/{os.getpid()}"


class LeaseLost(RuntimeError):
    """Another worker now owns this job. Stop, and write nothing."""


@dataclass(frozen=True)
class Lease:
    """Proof of which claim a worker is acting on.

    Taken at claim time and never re-read from the row, because the row is
    exactly what changes when the lease is lost: a stale worker that reloaded
    its job would see the new owner's attempt number and pass its own check.
    The attempt count is the fencing token — it increases on every claim, so
    two claims of one job can never hold the same lease, even from one process.
    """
    job_id: str
    attempt: int
    holder: str

    @classmethod
    def of(cls, job: Job) -> "Lease":
        return cls(job.id, job.attempts, job.leased_by)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(session: Session, kind: str, payload: dict[str, Any], *,
            priority: int = 100, run_after: datetime | None = None,
            max_attempts: int | None = None) -> Job:
    """Add a job. The caller commits, so the job and its subject land together.

    That atomicity is the point of keeping the queue in the same database: a
    media row can never exist without the job that processes it, and a job can
    never reference a row that was rolled back.
    """
    job = Job(
        kind=kind,
        payload=payload,
        priority=priority,
        run_after=run_after or _now(),
        max_attempts=max_attempts or settings().job_max_attempts,
    )
    session.add(job)
    session.flush()
    return job


def claim(session: Session, *, kinds: tuple[str, ...] | None = None,
          lease_seconds: int | None = None) -> Job | None:
    """Take one runnable job, or return None.

    Runnable means queued and due, or running with an expired lease — the second
    is how a job survives the worker that was holding it being killed.
    """
    lease = lease_seconds or settings().job_lease_seconds
    until = _now() + timedelta(seconds=lease)

    kind_filter = "AND kind = ANY(:kinds)" if kinds else ""
    row = session.execute(text(f"""
        UPDATE jobs SET
            state        = 'running',
            attempts     = attempts + 1,
            leased_until = :until,
            leased_by    = :worker
        WHERE id = (
            SELECT id FROM jobs
            WHERE (
                (state = 'queued'  AND run_after <= :now)
                OR
                -- Reclaim: the worker that held this is gone.
                (state = 'running' AND leased_until < :now)
            )
            {kind_filter}
            ORDER BY priority, run_after
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING id
    """), {"until": until, "worker": WORKER_ID, "now": _now(),
           **({"kinds": list(kinds)} if kinds else {})}).first()

    if row is None:
        return None
    session.commit()
    return session.get(Job, row[0])


def _fenced(session: Session, lease: Lease, values: dict) -> bool:
    """Update the job only if this lease still holds it. Does not commit.

    Every write a worker makes to its job goes through here. Without the fence,
    a worker whose lease lapsed — a long pause, a laptop lid, a slow provider —
    carries on and then marks done or re-queues a job another worker is midway
    through.
    """
    n = (session.query(Job)
         .filter(Job.id == lease.job_id,
                 Job.state == "running",
                 Job.attempts == lease.attempt,
                 Job.leased_by == lease.holder)
         .update(values, synchronize_session="fetch"))
    return n == 1


def extend(session: Session, lease: Lease, *,
           lease_seconds: int | None = None) -> None:
    """Push the lease out and commit, or raise LeaseLost."""
    seconds = lease_seconds or settings().job_lease_seconds
    if not _fenced(session, lease,
                   {"leased_until": _now() + timedelta(seconds=seconds)}):
        session.rollback()
        raise LeaseLost(f"job {lease.job_id} attempt {lease.attempt} "
                        f"is no longer held by {lease.holder}")
    session.commit()


def heartbeat(session: Session, job: Job, *, lease: Lease | None = None,
              lease_seconds: int | None = None) -> None:
    """Push the lease out. Raises LeaseLost if the job has been taken.

    The worker also extends the lease from a background thread, so a handler
    does not need to call this to stay alive. It calls it at stage boundaries
    so that a worker which has lost its job stops there, before it writes.
    """
    extend(session, lease or Lease.of(job), lease_seconds=lease_seconds)


def complete(session: Session, job: Job, *, lease: Lease | None = None) -> bool:
    """Mark the job done. False, and nothing written, if the lease was lost."""
    lease = lease or Lease.of(job)
    if not _fenced(session, lease, {"state": "done", "finished_at": _now(),
                                    "leased_until": None}):
        session.rollback()
        log.warning("[jobs] %s finished after losing its lease; another "
                    "worker owns it now", lease.job_id)
        return False
    session.commit()
    return True


def fail(session: Session, job: Job, error: str, *,
         lease: Lease | None = None,
         retry_in: timedelta | None = None,
         on_give_up: Callable[[Session], None] | None = None) -> bool:
    """Record a failure, and retry unless the attempts are used up.

    Backoff is exponential on the attempt count, because the common causes —
    a rate limit, a provider hiccup, a transient network fault — all resolve
    with time, and retrying immediately mostly burns the remaining attempts on
    the same condition.

    `on_give_up` runs only on the failure that ends the job, and in the same
    transaction as it. That is where refunds belong: a refund on every attempt
    pays back work that is about to be retried, and a refund committed
    separately is lost if the process dies between the two.

    Returns False, and writes nothing, if the lease was lost.
    """
    lease = lease or Lease.of(job)
    last_error = (error or "")[:4000]
    final = lease.attempt >= job.max_attempts

    if final:
        values = {"state": "failed", "finished_at": _now(),
                  "leased_until": None, "last_error": last_error}
    else:
        # `or` would be wrong here: timedelta(seconds=0) is falsy, so a
        # caller asking for an immediate retry would silently get the
        # backoff instead.
        delay = (retry_in if retry_in is not None
                 else timedelta(seconds=min(300, 10 * 2 ** lease.attempt)))
        values = {"state": "queued", "run_after": _now() + delay,
                  "leased_until": None, "last_error": last_error}

    if not _fenced(session, lease, values):
        session.rollback()
        log.warning("[jobs] %s failed after losing its lease; leaving it to "
                    "the worker that owns it: %s", lease.job_id, last_error)
        return False

    if final:
        log.error("[jobs] %s %s failed permanently after %d attempts: %s",
                  job.kind, job.id, lease.attempt, last_error)
        if on_give_up is not None:
            # In a savepoint: if the hook itself fails, the job must still end.
            # Otherwise the lease lapses, the job is reclaimed, fails, runs the
            # same broken hook, and loops every lease period forever.
            try:
                with session.begin_nested():
                    on_give_up(session)
            except Exception:
                log.exception("[jobs] give-up hook for %s %s failed",
                              job.kind, job.id)
    else:
        log.warning("[jobs] %s %s attempt %d/%d failed, retrying in %s: %s",
                    job.kind, job.id, lease.attempt, job.max_attempts,
                    delay, last_error)
    session.commit()
    return True


def stats(session: Session) -> dict[str, int]:
    rows = session.execute(text(
        "SELECT state, count(*) FROM jobs GROUP BY state"
    )).all()
    out = {"queued": 0, "running": 0, "done": 0, "failed": 0}
    out.update({state: int(n) for state, n in rows})
    return out
