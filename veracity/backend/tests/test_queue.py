"""The job queue, tested for the properties a durable queue actually needs.

Not "does enqueue insert a row" — that a queue stores things is uninteresting.
What matters is that two workers never get the same job, that a worker dying
mid-job does not lose it, and that a failing job eventually stops rather than
retrying forever.
"""
import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def clean_jobs(db):
    from app.db.session import owner_engine
    with owner_engine.begin() as c:
        c.execute(text("TRUNCATE jobs"))
    yield
    with owner_engine.begin() as c:
        c.execute(text("TRUNCATE jobs"))


class TestClaiming:
    def test_a_queued_job_is_claimed_and_completed(self, db):
        from app.db.session import owner_session
        from app.jobs import queue
        with owner_session() as s:
            queue.enqueue(s, "ingest", {"media_id": "m1"})
        with owner_session() as s:
            job = queue.claim(s)
            assert job is not None and job.kind == "ingest"
            assert job.state == "running" and job.attempts == 1
            queue.complete(s, job)
        with owner_session() as s:
            assert queue.claim(s) is None
            assert queue.stats(s)["done"] == 1

    def test_kinds_filter_is_honoured(self, db):
        from app.db.session import owner_session
        from app.jobs import queue
        with owner_session() as s:
            queue.enqueue(s, "analyze", {"a": 1})
        with owner_session() as s:
            assert queue.claim(s, kinds=("ingest",)) is None
            assert queue.claim(s, kinds=("analyze",)) is not None

    def test_priority_then_age_decides_order(self, db):
        from app.db.session import owner_session
        from app.jobs import queue
        with owner_session() as s:
            queue.enqueue(s, "ingest", {"n": "normal"}, priority=100)
            queue.enqueue(s, "ingest", {"n": "urgent"}, priority=1)
        with owner_session() as s:
            assert queue.claim(s).payload["n"] == "urgent"

    def test_a_job_scheduled_for_later_is_not_claimed_yet(self, db):
        from datetime import datetime, timezone
        from app.db.session import owner_session
        from app.jobs import queue
        later = datetime.now(timezone.utc) + timedelta(hours=1)
        with owner_session() as s:
            queue.enqueue(s, "ingest", {"x": 1}, run_after=later)
        with owner_session() as s:
            assert queue.claim(s) is None


class TestConcurrency:
    def test_ten_workers_never_get_the_same_job_twice(self, db):
        """FOR UPDATE SKIP LOCKED is the whole reason this queue is safe.
        Without it, two workers transcribe the same hour of audio and the user
        is billed twice for one answer."""
        from app.db.session import owner_session
        from app.jobs import queue

        n_jobs, n_workers = 20, 10
        with owner_session() as s:
            for i in range(n_jobs):
                queue.enqueue(s, "ingest", {"i": i})

        claimed: list[str] = []
        lock = threading.Lock()
        barrier = threading.Barrier(n_workers)

        def worker():
            barrier.wait()                 # start together, maximise contention
            while True:
                with owner_session() as s:
                    job = queue.claim(s)
                    if job is None:
                        return
                    with lock:
                        claimed.append(job.id)
                    queue.complete(s, job)

        threads = [threading.Thread(target=worker) for _ in range(n_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(claimed) == n_jobs, "some jobs were never claimed"
        assert len(set(claimed)) == n_jobs, "a job was handed to two workers"


class TestRecovery:
    def test_an_expired_lease_is_reclaimed(self, db):
        """A worker killed mid-job must not strand it. This is the defect the
        whole design exists to avoid: Cognita's equivalent leaves the row in
        'processing' until a reaper gives up on it."""
        from app.db.session import owner_session
        from app.jobs import queue
        with owner_session() as s:
            queue.enqueue(s, "ingest", {"x": 1})
        with owner_session() as s:
            first = queue.claim(s, lease_seconds=1)
            assert first is not None
        # The worker holding it dies here, without completing or failing.
        with owner_session() as s:
            assert queue.claim(s) is None, "claimed while the lease was live"
        time.sleep(1.2)
        with owner_session() as s:
            second = queue.claim(s)
            assert second is not None and second.id == first.id
            assert second.attempts == 2, "a reclaim must count as an attempt"

    def test_heartbeat_holds_the_lease_open(self, db):
        from app.db.session import owner_session
        from app.jobs import queue
        with owner_session() as s:
            queue.enqueue(s, "ingest", {"x": 1})
        with owner_session() as s:
            job = queue.claim(s, lease_seconds=1)
            time.sleep(0.6)
            queue.heartbeat(s, job, lease_seconds=60)
        time.sleep(0.6)
        with owner_session() as s:
            assert queue.claim(s) is None, "reclaimed despite a heartbeat"

    def test_a_failure_retries_with_backoff_then_gives_up(self, db):
        from app.db.session import owner_session
        from app.jobs import queue
        with owner_session() as s:
            queue.enqueue(s, "ingest", {"x": 1}, max_attempts=2)

        with owner_session() as s:
            job = queue.claim(s)
            queue.fail(s, job, "provider timed out",
                       retry_in=timedelta(seconds=0))
            assert job.state == "queued", "first failure should retry"

        with owner_session() as s:
            job = queue.claim(s)
            assert job.attempts == 2
            queue.fail(s, job, "provider timed out again")
            assert job.state == "failed", "must stop at max_attempts"
            assert "provider timed out" in job.last_error

        with owner_session() as s:
            assert queue.claim(s) is None
            assert queue.stats(s)["failed"] == 1


class TestFencing:
    """A worker that has lost its lease must not write to the job.

    Leases lapse in practice — a long pause, a laptop lid, a slow provider —
    and the worker holding one does not know. Without a fence it carries on and
    then marks done, or re-queues, a job another worker is midway through.
    """

    def _stolen(self, lease_seconds=1):
        """Claim a job, let the lease lapse, and have a second claim take it."""
        from app.db.session import owner_session
        from app.jobs import queue
        with owner_session() as s:
            queue.enqueue(s, "ingest", {"x": 1})
        with owner_session() as s:
            first = queue.claim(s, lease_seconds=lease_seconds)
        time.sleep(lease_seconds + 0.2)
        with owner_session() as s:
            second = queue.claim(s, lease_seconds=60)
        assert second.id == first.id and second.attempts == 2
        return first

    def test_a_lost_lease_cannot_complete_the_job(self, db):
        from app.db.session import owner_session
        from app.db.models import Job
        from app.jobs import queue
        first = self._stolen()
        with owner_session() as s:
            assert queue.complete(s, first) is False
        with owner_session() as s:
            job = s.query(Job).one()
            assert job.state == "running" and job.attempts == 2

    def test_a_lost_lease_cannot_requeue_the_job(self, db):
        from app.db.session import owner_session
        from app.db.models import Job
        from app.jobs import queue
        first = self._stolen()
        with owner_session() as s:
            assert queue.fail(s, first, "late failure") is False
        with owner_session() as s:
            job = s.query(Job).one()
            assert job.state == "running" and job.last_error is None

    def test_a_heartbeat_on_a_lost_lease_raises(self, db):
        from app.db.session import owner_session
        from app.jobs import queue
        first = self._stolen()
        with owner_session() as s:
            with pytest.raises(queue.LeaseLost):
                queue.heartbeat(s, first)

    def test_the_lease_is_the_claim_not_the_row(self, db):
        """Reloading the row would read the new owner's attempt number and pass
        the check. The lease is taken once, at claim time."""
        from app.db.session import owner_session
        from app.jobs import queue
        with owner_session() as s:
            queue.enqueue(s, "ingest", {"x": 1})
        with owner_session() as s:
            job = queue.claim(s, lease_seconds=1)
            lease = queue.Lease.of(job)
        time.sleep(1.2)
        with owner_session() as s:
            queue.claim(s, lease_seconds=60)
        with owner_session() as s:
            fresh = s.get(type(job), job.id)          # attempts == 2 now
            assert queue.complete(s, fresh, lease=lease) is False


class TestGivingUp:
    def test_the_hook_runs_on_the_final_failure_only(self, db):
        from app.db.session import owner_session
        from app.jobs import queue
        calls = []
        with owner_session() as s:
            queue.enqueue(s, "ingest", {"x": 1}, max_attempts=2)
        with owner_session() as s:
            job = queue.claim(s)
            queue.fail(s, job, "first", retry_in=timedelta(0),
                       on_give_up=lambda _s: calls.append(1))
        assert calls == [], "a failure that will be retried must not give up"
        with owner_session() as s:
            job = queue.claim(s)
            queue.fail(s, job, "second", on_give_up=lambda _s: calls.append(2))
        assert calls == [2]

    def test_the_hook_commits_with_the_failure(self, db):
        """A refund committed separately is lost if the process dies between
        the two writes. It goes in the transaction that ends the job."""
        from app.db.session import owner_session
        from app.jobs import queue
        with owner_session() as s:
            queue.enqueue(s, "ingest", {"x": 1}, max_attempts=1)
        with owner_session() as s:
            job = queue.claim(s)
            queue.fail(s, job, "boom", on_give_up=lambda gs: gs.execute(text(
                "UPDATE jobs SET payload = '{\"refunded\": true}'")))
        with owner_session() as s:
            row = s.execute(text("SELECT state, payload FROM jobs")).one()
            assert row[0] == "failed" and row[1] == {"refunded": True}

    def test_a_broken_hook_still_ends_the_job(self, db):
        """Otherwise the lease lapses, the job is reclaimed, fails, runs the
        same broken hook, and loops every lease period forever."""
        from app.db.session import owner_session
        from app.jobs import queue

        def broken(_s):
            raise RuntimeError("refund service down")

        with owner_session() as s:
            queue.enqueue(s, "ingest", {"x": 1}, max_attempts=1)
        with owner_session() as s:
            job = queue.claim(s)
            assert queue.fail(s, job, "boom", on_give_up=broken) is True
        with owner_session() as s:
            assert queue.stats(s)["failed"] == 1
            assert queue.claim(s) is None
