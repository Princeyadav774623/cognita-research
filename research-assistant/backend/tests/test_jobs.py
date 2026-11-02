"""The research queue, against real Postgres.

The properties that matter here are all about concurrency and failure — one
claim per job, a worker that lost its job writing nothing, a reconnecting
client seeing each event exactly once — and none of them can be shown with a
mocked session. Needs DATABASE_URL and APP_DATABASE_URL, as CI provides.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import jobs
import worker
from billing import init_billing_db
from db import engine, init_db
from rag.store import init_rag_db
from rls import apply_rls_policies

PREFIX = "jobtest-"


@pytest.fixture(scope="module", autouse=True)
def schema():
    init_db(); init_billing_db(); init_rag_db(); apply_rls_policies()


@pytest.fixture(autouse=True)
def clean():
    def wipe():
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM research_jobs WHERE user_id LIKE :p"), {"p": PREFIX + "%"})
            conn.execute(text("DELETE FROM user_subscriptions WHERE user_id LIKE :p"), {"p": PREFIX + "%"})
    wipe()
    yield
    wipe()


def _user() -> str:
    return PREFIX + uuid.uuid4().hex[:8]


def _queued(query: str = "why is the sky blue") -> tuple[str, str]:
    user, job_id = _user(), str(uuid.uuid4())
    jobs.enqueue(user, job_id, query)
    return user, job_id


def _set(job_id: str, **values) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE research_jobs SET {sets} WHERE id = :id"), {**values, "id": job_id})


def _past() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=5)


def _types(user: str, job_id: str) -> list[str]:
    return [p["type"] for _, p in jobs.events_after(user, job_id, 0)]


class TestClaiming:
    def test_a_job_is_claimed_once(self):
        user, job_id = _queued()
        lease = jobs.claim()
        assert lease.job_id == job_id and lease.user_id == user and lease.attempt == 1
        assert jobs.claim() is None
        assert jobs.get_job(user, job_id)["state"] == "running"

    def test_a_lapsed_lease_is_reclaimed_and_the_old_worker_fenced_out(self):
        user, job_id = _queued()
        old = jobs.claim()
        _set(job_id, leased_until=_past())

        new = jobs.claim()
        assert new.attempt == 2

        with pytest.raises(jobs.LeaseLost):
            jobs.append(old, [{"type": "progress"}])
        assert not jobs.complete(old, {"type": "complete"})
        jobs.append(new, [{"type": "progress"}])
        assert _types(user, job_id) == ["progress"]

    def test_release_hands_the_job_back_without_spending_an_attempt(self):
        user, job_id = _queued()
        assert jobs.release(jobs.claim())
        assert jobs.claim().attempt == 1
        assert _types(user, job_id) == ["restart"]


class TestOutcomes:
    def test_a_failure_retries_then_gives_up(self):
        user, job_id = _queued()
        assert jobs.fail(jobs.claim(), "boom") == "retry"
        assert jobs.get_job(user, job_id)["state"] == "queued"

        _set(job_id, run_after=_past())
        lease = jobs.claim()
        assert lease.attempt == 2
        assert jobs.fail(lease, "boom again") == "failed"
        assert jobs.get_job(user, job_id)["state"] == "failed"
        assert _types(user, job_id) == ["restart", "error"]

    def test_a_dead_worker_on_the_last_attempt_is_reaped(self):
        user, job_id = _queued()
        jobs.claim()
        _set(job_id, leased_until=_past(), max_attempts=1)

        assert jobs.claim() is None  # out of attempts, so not reclaimed
        assert jobs.reap_exhausted() == [user]
        assert jobs.get_job(user, job_id)["state"] == "failed"
        assert _types(user, job_id) == ["error"]

    def test_cancel_stops_the_worker_at_its_next_write(self):
        user, job_id = _queued()
        lease = jobs.claim()

        assert jobs.cancel(user, job_id)
        assert not jobs.cancel(user, job_id)  # already stopped
        with pytest.raises(jobs.LeaseLost):
            jobs.append(lease, [{"type": "progress"}])
        assert not jobs.complete(lease, {"type": "complete"})
        assert jobs.get_job(user, job_id)["state"] == "cancelled"


class TestEvents:
    def test_events_resume_after_a_cursor(self):
        user, job_id = _queued()
        lease = jobs.claim()
        jobs.append(lease, [{"type": "progress", "n": 1}, {"type": "progress", "n": 2}])

        events = jobs.events_after(user, job_id, 0)
        assert [p["n"] for _, p in events] == [1, 2]
        first_seq = events[0][0]
        assert [p["n"] for _, p in jobs.events_after(user, job_id, first_seq)] == [2]

    def test_another_tenant_sees_neither_the_job_nor_its_events(self):
        user, job_id = _queued()
        jobs.append(jobs.claim(), [{"type": "progress"}])

        intruder = _user()
        assert jobs.get_job(intruder, job_id) is None
        assert jobs.events_after(intruder, job_id, 0) == []
        assert not jobs.cancel(intruder, job_id)


class TestWorker:
    @pytest.mark.asyncio
    async def test_a_run_publishes_its_progress_and_saves_the_report(self, monkeypatch):
        async def fake_stream(query, session_id, user_id=None):
            yield {"type": "token", "node": "report", "text": "Hello "}
            yield {"type": "token", "node": "report", "text": "world"}
            yield {"node": "report", "step": "report", "data": {"message": "done"},
                   "state": {"final_report": "Hello world"}}

        saved = {}
        monkeypatch.setattr(worker, "stream_research", fake_stream)
        monkeypatch.setattr(worker, "save_session",
                            lambda sid, uid, q, state: saved.update(sid=sid, state=state))

        user, job_id = _queued()
        await worker.run_job(jobs.claim())

        events = [p for _, p in jobs.events_after(user, job_id, 0)]
        # Consecutive tokens from one node are batched into one event.
        assert events[0] == {"type": "token", "node": "report", "text": "Hello world"}
        assert [e["type"] for e in events] == ["token", "progress", "complete"]
        assert saved["sid"] == job_id
        assert saved["state"]["final_report"] == "Hello world"
        assert jobs.get_job(user, job_id)["state"] == "done"

    @pytest.mark.asyncio
    async def test_only_the_attempt_that_gives_up_refunds(self, monkeypatch):
        async def broken_stream(query, session_id, user_id=None):
            raise RuntimeError("provider down")
            yield  # pragma: no cover — makes this an async generator

        refunds = []
        monkeypatch.setattr(worker, "stream_research", broken_stream)
        monkeypatch.setattr(worker, "refund_quota", refunds.append)

        user, job_id = _queued()
        await worker.run_job(jobs.claim())
        assert refunds == []  # a retry is still coming
        assert jobs.get_job(user, job_id)["state"] == "queued"

        _set(job_id, run_after=_past())
        await worker.run_job(jobs.claim())
        assert refunds == [user]
        assert jobs.get_job(user, job_id)["state"] == "failed"


class TestWebSocket:
    def _client(self, monkeypatch, user):
        from fastapi.testclient import TestClient
        import api.main as main

        monkeypatch.setattr(main, "verify_token", lambda token: {"sub": user})
        # Not entered as a context manager, so the lifespan (migrations,
        # embedding warm-up) does not run — the schema fixture has done it.
        return TestClient(main.app)

    def test_a_dropped_client_resumes_where_it_left_off(self, monkeypatch):
        user, job_id = _user(), str(uuid.uuid4())
        client = self._client(monkeypatch, user)

        with client.websocket_connect("/ws/research") as ws:
            ws.send_json({"token": "t", "query": "why is the sky blue", "session_id": job_id})
            assert ws.receive_json()["type"] == "start"

            lease = jobs.claim()
            assert lease.job_id == job_id
            jobs.append(lease, [{"type": "progress", "node": "search"}])
            progress = ws.receive_json()
            assert progress["type"] == "progress" and progress["seq"] > 0
        # Disconnected mid-run. The research is unaffected.
        assert jobs.get_job(user, job_id)["state"] == "running"

        jobs.complete(lease, {"type": "complete", "session_id": job_id})
        with client.websocket_connect("/ws/research") as ws:
            # Same id, so this attaches rather than queueing a second run.
            ws.send_json({"token": "t", "query": "why is the sky blue",
                          "session_id": job_id, "after": progress["seq"]})
            assert ws.receive_json()["type"] == "start"
            assert ws.receive_json()["type"] == "complete"

        with engine.connect() as conn:
            used = conn.execute(text(
                "SELECT monthly_queries_used FROM user_subscriptions WHERE user_id = :u"
            ), {"u": user}).scalar()
        assert used == 1  # charged once, for one run, across two connections
