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

import logging
import signal
import sys
import time

from app.config import settings
from app.db.session import owner_session
from app.jobs import queue
from app.jobs.handlers import HANDLERS

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


def run(kinds: tuple[str, ...] | None = None, *, once: bool = False) -> int:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    log.info("[worker] %s started, kinds=%s", queue.WORKER_ID, kinds or "all")
    processed = 0

    while not _stop:
        with owner_session() as session:
            job = queue.claim(session, kinds=kinds)

        if job is None:
            if once:
                break
            time.sleep(settings().worker_poll_seconds)
            continue

        handler = HANDLERS.get(job.kind)
        with owner_session() as session:
            live = session.get(type(job), job.id)
            if handler is None:
                queue.fail(session, live, f"no handler for kind {job.kind!r}")
                continue

            started = time.monotonic()
            try:
                handler(session, job.payload,
                        lambda: queue.heartbeat(session, live))
            except Exception as exc:
                log.exception("[worker] %s %s raised", job.kind, job.id)
                queue.fail(session, live, f"{type(exc).__name__}: {exc}")
            else:
                queue.complete(session, live)
                processed += 1
                log.info("[worker] %s %s done in %.1fs",
                         job.kind, job.id, time.monotonic() - started)
        if once:
            break

    log.info("[worker] stopped after %d job(s)", processed)
    return processed


def main() -> None:  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    kinds = tuple(sys.argv[1:]) or None
    run(kinds)


if __name__ == "__main__":  # pragma: no cover
    main()
