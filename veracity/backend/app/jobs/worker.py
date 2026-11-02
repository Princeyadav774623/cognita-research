"""The worker loop.

Deliberately dull. Claim, dispatch, mark done or failed, repeat. Every decision
worth making — whether to retry, how long to back off, when to give up — lives
in `queue`, and every decision about the work lives in `handlers`. What is left
here is the part that must never be clever, because it is the part that runs
unattended.

Runs as the owner: it has no user context when it claims work, so it cannot be
constrained by the policies that scope requests. Each handler scopes itself to
the row it is working on.
"""
from __future__ import annotations

import contextvars
import logging
import signal
import sys
import threading
import time

from app.config import settings
from app.db.session import owner_session
from app.jobs import queue
from app.jobs.handlers import GIVE_UP, HANDLERS

log = logging.getLogger("worker")

_stop = False


def _request_stop(signum, _frame):
    """Finish the job in hand, then exit.

    Killing mid-job would be survivable — the lease expires and another worker
    picks it up — but it wastes the work already done, and for transcription
    that can be minutes of provider time.
    """
    global _stop
    _stop = True
    log.info("[worker] signal %s received, finishing the current job", signum)


class _LeaseKeeper:
    """Extends a job's lease from a background thread while its handler runs.

    Heartbeats placed by hand always miss something. A download is one
    subprocess call that can run for half an hour; an analysis is dozens of
    provider calls whose retries sleep. Any gap longer than the lease hands the
    job to a second worker, which does the work again and pays for it again.
    A timer covers every step, including ones not written yet.

    Capped at `job_max_runtime_seconds`, so a handler that hangs does not hold
    its job forever: past the cap the lease lapses and another worker retries.
    """

    def __init__(self, lease: queue.Lease):
        cfg = settings()
        self.lease = lease
        self._interval = max(0.1, cfg.job_lease_seconds / 3)
        self._deadline = time.monotonic() + cfg.job_max_runtime_seconds
        self._stop = threading.Event()
        # Run inside a copy of this context so its log lines carry the job id.
        ctx = contextvars.copy_context()
        self._thread = threading.Thread(target=ctx.run, args=(self._run,),
                                        name=f"lease-{lease.job_id[:8]}",
                                        daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._stop.set()
        self._thread.join()
        return False

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            if time.monotonic() > self._deadline:
                log.error("[worker] %s has run past %ss; no longer extending "
                          "its lease", self.lease.job_id,
                          settings().job_max_runtime_seconds)
                return
            try:
                with owner_session() as s:
                    queue.extend(s, self.lease)
            except queue.LeaseLost:
                log.warning("[worker] lost the lease on %s", self.lease.job_id)
                return
            except Exception as exc:
                # Most likely a database blip. Extending at a third of the
                # lease leaves two more tries before it actually lapses.
                log.warning("[worker] could not extend the lease on %s: %s",
                            self.lease.job_id, exc)


def run(kinds: tuple[str, ...] | None = None, *, once: bool = False) -> int:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    log.info("[worker] %s started, kinds=%s", queue.WORKER_ID, kinds or "all")
    processed = 0

    while not _stop:
        with owner_session() as session:
            job = queue.claim(session, kinds=kinds)
            lease = queue.Lease.of(job) if job is not None else None

        if job is None:
            if once:
                break
            time.sleep(settings().worker_poll_seconds)
            continue

        handler = HANDLERS.get(job.kind)
        with owner_session() as session:
            live = session.get(type(job), job.id)
            if handler is None:
                queue.fail(session, live, f"no handler for kind {job.kind!r}",
                           lease=lease)
                continue

            from app.observability import job_id as job_ctx, metrics
            token = job_ctx.set(job.id)
            started = time.monotonic()
            try:
                with _LeaseKeeper(lease):
                    handler(session, job.payload,
                            lambda: queue.heartbeat(session, live, lease=lease))
            except queue.LeaseLost:
                session.rollback()
                outcome = "lease_lost"
                log.warning("[worker] %s %s lost its lease; stopped without "
                            "writing its result", job.kind, job.id)
            except Exception as exc:
                log.exception("[worker] %s %s raised", job.kind, job.id)
                # A failed statement leaves the transaction unusable until it is
                # rolled back. The handler has already committed its own record
                # of what went wrong, so nothing is lost by doing so.
                session.rollback()
                give_up = GIVE_UP.get(job.kind)
                payload = job.payload
                queue.fail(session, live, f"{type(exc).__name__}: {exc}",
                           lease=lease,
                           on_give_up=((lambda s: give_up(s, payload))
                                       if give_up else None))
                outcome = "failed"
            else:
                done = queue.complete(session, live, lease=lease)
                outcome = "done" if done else "lease_lost"
                if done:
                    processed += 1
                    elapsed = time.monotonic() - started
                    metrics.observe("veracity_job_seconds", elapsed,
                                    "Time to run a job", kind=job.kind)
                    log.info("[worker] %s %s done in %.1fs",
                             job.kind, job.id, elapsed)
            finally:
                job_ctx.reset(token)
            metrics.count("veracity_jobs_total", "Jobs finished",
                          kind=job.kind, outcome=outcome)
        if once:
            break

    log.info("[worker] stopped after %d job(s)", processed)
    return processed


def main() -> None:  # pragma: no cover
    import os

    from app.observability import configure
    configure(level=os.getenv("LOG_LEVEL", "INFO"),
              json_logs=os.getenv("LOG_FORMAT", "json") == "json")
    kinds = tuple(sys.argv[1:]) or None
    run(kinds)


if __name__ == "__main__":  # pragma: no cover
    main()
