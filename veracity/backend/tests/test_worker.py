"""The worker, including the paths that go wrong.

The happy path is the easy half. What a background worker has to get right is
what happens when the source is gone, when a handler raises, and when the same
job is delivered twice — because those are the states a restart actually
produces.
"""
import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def clean(db):
    from app.db.session import owner_engine
    with owner_engine.begin() as c:
        c.execute(text("TRUNCATE jobs, media_items CASCADE"))
    yield


def _queue_media(user: str, source_path: str | None):
    """Put a file in storage and queue it, as the upload route does.

    `None` stands for a row whose file is missing — the race where a worker
    picks a job up before the upload finished, or the file was deleted under it.
    """
    from app.db.session import app_session, owner_session
    from app.db.models import MediaItem, MediaState
    from app.jobs import queue
    from app.storage import source_key, storage

    with app_session(user) as s:
        m = MediaItem(user_id=user, source_kind="upload",
                      original_filename=(os.path.basename(source_path)
                                         if source_path else "gone.mp4"),
                      state=MediaState.pending)
        s.add(m); s.flush()
        media_id = m.id

    if source_path:
        key = source_key(media_id, os.path.basename(source_path))
        storage().put(key, source_path)
        with app_session(user) as s:
            item = s.get(MediaItem, media_id)
            item.source_key = key
            s.add(item)
    with owner_session() as s:
        queue.enqueue(s, "ingest", {"media_id": media_id})
    return media_id


class TestIngestJob:
    def test_media_reaches_ready_with_timed_chunks(self, db, tone_media, stub_asr):
        """Tone rather than speech: the point is that the pipeline completes and
        the timing survives, not what the words were."""
        from app.db.session import app_session
        from app.db.models import MediaItem, MediaState, TranscriptChunk
        from app.jobs import worker

        media_id = _queue_media("user-w1", tone_media)
        assert worker.run(kinds=("ingest",), once=True) == 1

        with app_session("user-w1") as s:
            m = s.get(MediaItem, media_id)
            assert m.state == MediaState.ready
            assert m.duration_ms == pytest.approx(30_000, abs=300)
            assert m.has_video is True
            assert m.error is None
            chunks = s.query(TranscriptChunk).filter_by(media_id=media_id).all()
            for c in chunks:
                assert c.end_ms >= c.start_ms
                assert 0 <= c.start_ms <= m.duration_ms + 1000

    def test_a_missing_source_fails_the_media_and_says_why(self, db):
        from app.db.session import app_session, owner_session
        from app.db.models import MediaItem, MediaState, Job
        from app.jobs import worker

        media_id = _queue_media("user-w2", None)
        worker.run(kinds=("ingest",), once=True)

        with app_session("user-w2") as s:
            m = s.get(MediaItem, media_id)
            assert m.state == MediaState.failed
            assert "no stored file" in m.error

        with owner_session() as s:
            job = s.query(Job).first()
            # Retried rather than abandoned: a missing file is usually a race
            # with an upload still being written, not a permanent condition.
            assert job.state == "queued"
            assert job.attempts == 1
            assert "no stored file" in job.last_error

    def test_a_silent_file_is_refused_before_any_transcription(self, db, silent_media):
        from app.db.session import app_session
        from app.db.models import MediaItem, MediaState
        from app.jobs import worker

        media_id = _queue_media("user-w3", silent_media)
        worker.run(kinds=("ingest",), once=True)
        with app_session("user-w3") as s:
            m = s.get(MediaItem, media_id)
            assert m.state == MediaState.failed
            assert "no audio track" in m.error

    def test_redelivery_of_a_finished_item_is_a_no_op(self, db, tone_media, stub_asr):
        """A lease can expire on a job whose work already landed. Re-running it
        must not transcribe the media a second time and bill for it twice."""
        from app.db.session import app_session, owner_session
        from app.db.models import MediaItem, MediaState, TranscriptChunk
        from app.jobs import queue, worker

        media_id = _queue_media("user-w4", tone_media)
        worker.run(kinds=("ingest",), once=True)
        with app_session("user-w4") as s:
            before = s.query(TranscriptChunk).filter_by(media_id=media_id).count()
            assert s.get(MediaItem, media_id).state == MediaState.ready

        with owner_session() as s:
            queue.enqueue(s, "ingest", {"media_id": media_id})
        worker.run(kinds=("ingest",), once=True)

        with app_session("user-w4") as s:
            assert s.query(TranscriptChunk).filter_by(media_id=media_id).count() == before

    def test_an_unknown_job_kind_fails_rather_than_crashing_the_loop(self, db):
        from app.db.session import owner_session
        from app.db.models import Job
        from app.jobs import queue, worker
        with owner_session() as s:
            queue.enqueue(s, "not-a-real-kind", {}, max_attempts=1)
        worker.run(once=True)
        with owner_session() as s:
            job = s.query(Job).first()
            assert job.state == "failed"
            assert "no handler" in job.last_error


class TestFetchJob:
    def test_a_url_item_is_downloaded_then_ingested(self, db, tone_media,
                                                    stub_asr, monkeypatch):
        """Fetch chains into ingest in the same worker, because the file it
        downloaded is on this worker's disk and nowhere else."""
        import shutil

        from app.db.session import app_session, owner_session
        from app.db.models import MediaItem, MediaState
        from app.ingest import resolve as resolve_mod
        from app.jobs import queue, worker

        def fake_fetch(url, dest_dir, **_):
            import os
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, "source.mp4")
            shutil.copy(tone_media, dest)
            return resolve_mod.Resolved(path=dest, title="A Talk",
                                        author="Someone", duration_ms=30_000,
                                        webpage_url=url)

        monkeypatch.setattr(resolve_mod, "fetch", fake_fetch)

        with app_session("user-f1") as s:
            m = MediaItem(user_id="user-f1", source_kind="url",
                          source_url="https://example.com/talk",
                          state=MediaState.pending)
            s.add(m); s.flush()
            media_id = m.id
        with owner_session() as s:
            queue.enqueue(s, "fetch", {"media_id": media_id})

        assert worker.run(kinds=("fetch",), once=True) == 1
        with app_session("user-f1") as s:
            m = s.get(MediaItem, media_id)
            assert m.state == MediaState.ready
            assert m.title == "A Talk"
            assert m.author == "Someone"

    def test_a_refused_url_fails_the_media_with_the_reason(self, db, monkeypatch):
        from app.db.session import app_session, owner_session
        from app.db.models import MediaItem, MediaState
        from app.ingest import resolve as resolve_mod
        from app.jobs import queue, worker

        def refuse(url, dest_dir, **_):
            raise resolve_mod.ResolveError("that video is unavailable")

        monkeypatch.setattr(resolve_mod, "fetch", refuse)

        with app_session("user-f2") as s:
            m = MediaItem(user_id="user-f2", source_kind="url",
                          source_url="https://example.com/gone",
                          state=MediaState.pending)
            s.add(m); s.flush()
            media_id = m.id
        with owner_session() as s:
            queue.enqueue(s, "fetch", {"media_id": media_id})

        worker.run(kinds=("fetch",), once=True)
        with app_session("user-f2") as s:
            m = s.get(MediaItem, media_id)
            assert m.state == MediaState.failed
            assert "unavailable" in m.error


def _used(user: str, meter: str) -> float:
    from app.db.session import owner_session
    with owner_session() as s:
        row = s.execute(text(f"SELECT {meter} FROM user_quotas WHERE user_id = :u"),
                        {"u": user}).first()
    return float(row[0]) if row else 0.0


def _charge(user: str, meter: str, amount: float) -> None:
    from app.db.session import app_session
    from app.quota import consume
    with app_session(user) as s:
        consume(s, user, meter=meter, amount=amount)


def _url_item(user: str, max_attempts: int = 1) -> str:
    """A URL submission, charged its nominal minute exactly as the route does."""
    from app.db.session import app_session, owner_session
    from app.db.models import MediaItem, MediaState
    from app.jobs import queue
    _charge(user, "transcription_minutes", 1.0)
    with app_session(user) as s:
        m = MediaItem(user_id=user, source_kind="url",
                      source_url="https://example.com/talk",
                      state=MediaState.pending)
        s.add(m); s.flush()
        media_id = m.id
    with owner_session() as s:
        queue.enqueue(s, "fetch", {"media_id": media_id},
                      max_attempts=max_attempts)
    return media_id


def _ready_media_with_analysis(user: str, mode, max_attempts: int) -> str:
    from app.db.session import app_session, owner_session
    from app.db.models import (Analysis, AnalysisState, MediaItem, MediaState,
                               TranscriptSegment)
    from app.jobs import queue
    from app.quota import CREDITS
    with app_session(user) as s:
        m = MediaItem(user_id=user, source_kind="upload",
                      original_filename="talk.mp4", state=MediaState.ready)
        s.add(m); s.flush()
        s.add(TranscriptSegment(media_id=m.id, ordinal=0, start_ms=0,
                                end_ms=1000, text="the reef", confidence=0.9))
        a = Analysis(media_id=m.id, user_id=user, mode=mode,
                     state=AnalysisState.queued)
        s.add(a); s.flush()
        analysis_id = a.id
    _charge(user, "analysis_credits", CREDITS[mode])
    with owner_session() as s:
        queue.enqueue(s, "analyze", {"analysis_id": analysis_id},
                      max_attempts=max_attempts)
    return analysis_id


class TestRefunds:
    """Allowance comes back when a job fails for the last time, and not before.

    Keyed on the job kind the user was charged through. A URL item runs its
    ingest inside the fetch job, so it never has an ingest job of its own — the
    refund used to look for one, find nothing, and keep the user's minutes.
    """

    def test_a_url_item_that_fails_to_ingest_is_refunded(self, db, silent_media,
                                                          monkeypatch):
        import shutil

        from app.db.session import app_session
        from app.db.models import MediaItem, MediaState
        from app.ingest import resolve as resolve_mod
        from app.jobs import worker

        def fake_fetch(url, dest_dir, **_):
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, "source.mp4")
            shutil.copy(silent_media, dest)
            return resolve_mod.Resolved(path=dest, title=None, author=None,
                                        duration_ms=None, webpage_url=url)

        monkeypatch.setattr(resolve_mod, "fetch", fake_fetch)
        media_id = _url_item("user-r1")
        assert _used("user-r1", "transcription_minutes") == 1.0

        worker.run(kinds=("fetch",), once=True)

        with app_session("user-r1") as s:
            assert s.get(MediaItem, media_id).state == MediaState.failed
        assert _used("user-r1", "transcription_minutes") == 0.0

    def test_a_url_that_cannot_be_fetched_is_refunded(self, db, monkeypatch):
        from app.ingest import resolve as resolve_mod
        from app.jobs import worker

        def refuse(url, dest_dir, **_):
            raise resolve_mod.ResolveError("that video is unavailable")

        monkeypatch.setattr(resolve_mod, "fetch", refuse)
        _url_item("user-r2")
        worker.run(kinds=("fetch",), once=True)
        assert _used("user-r2", "transcription_minutes") == 0.0

    def test_a_failed_analysis_refunds_its_credits(self, db, monkeypatch):
        from app.db.session import app_session
        from app.db.models import Analysis, AnalysisMode, AnalysisState
        from app.jobs import worker

        def provider_down(*_a, **_k):
            raise RuntimeError("provider error 503")

        monkeypatch.setattr("app.analysis.pipeline.run", provider_down)
        analysis_id = _ready_media_with_analysis("user-r3", AnalysisMode.deep,
                                                 max_attempts=1)
        assert _used("user-r3", "analysis_credits") == 4

        worker.run(kinds=("analyze",), once=True)

        with app_session("user-r3") as s:
            assert s.get(Analysis, analysis_id).state == AnalysisState.failed
        assert _used("user-r3", "analysis_credits") == 0

    def test_a_failure_that_will_be_retried_keeps_the_charge(self, db,
                                                             monkeypatch):
        """Refunding every attempt would hand back allowance for work that is
        about to run again, and three failed tries would each be free."""
        from app.db.models import AnalysisMode
        from app.jobs import worker

        monkeypatch.setattr("app.analysis.pipeline.run",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("rate limited")))
        _ready_media_with_analysis("user-r4", AnalysisMode.deep, max_attempts=2)
        worker.run(kinds=("analyze",), once=True)
        assert _used("user-r4", "analysis_credits") == 4


@pytest.fixture
def short_leases(monkeypatch):
    """One-second leases, so lease behaviour can be observed in a test."""
    import dataclasses

    from app.config import settings

    def apply(**overrides):
        short = dataclasses.replace(settings(), job_lease_seconds=1,
                                    **overrides)
        monkeypatch.setattr("app.jobs.queue.settings", lambda: short)
        monkeypatch.setattr("app.jobs.worker.settings", lambda: short)
    return apply


def _watch_for_theft(stop, stolen):
    """A second worker, polling for the job the first is supposed to hold."""
    import time as _t

    from app.db.session import owner_session
    from app.jobs import queue
    while not stop.is_set():
        with owner_session() as s:
            # Only once the first worker holds it: a queued job is fair game,
            # and claiming it first would not be theft.
            held = s.execute(text(
                "SELECT 1 FROM jobs WHERE state = 'running'")).first()
            job = (queue.claim(s, kinds=("slow",), lease_seconds=60)
                   if held else None)
        if job is not None:
            stolen.append(job.attempts)
            return
        _t.sleep(0.1)


class TestLeases:
    def test_a_job_longer_than_its_lease_is_not_taken_by_another_worker(
            self, db, short_leases, monkeypatch):
        """The failure this prevents is paying twice. Without the background
        keeper, any stage longer than the lease — a download, a long analysis —
        hands the job to a second worker that starts it again."""
        import threading
        import time as _t

        from app.db.session import owner_session
        from app.db.models import Job
        from app.jobs import handlers, queue, worker

        short_leases(job_max_runtime_seconds=60)
        monkeypatch.setitem(handlers.HANDLERS, "slow",
                            lambda s, p, hb: _t.sleep(3))
        with owner_session() as s:
            queue.enqueue(s, "slow", {})

        stop, stolen = threading.Event(), []
        thief = threading.Thread(target=_watch_for_theft, args=(stop, stolen))
        thief.start()
        try:
            assert worker.run(kinds=("slow",), once=True) == 1
        finally:
            stop.set(); thief.join()

        assert stolen == [], "a second worker took a job that was still running"
        with owner_session() as s:
            job = s.query(Job).one()
            assert job.state == "done" and job.attempts == 1

    def test_a_hung_job_is_released_and_its_late_result_discarded(
            self, db, short_leases, monkeypatch):
        """The keeper stops at the runtime cap, so a hung handler cannot hold its
        job forever. When the original worker finally returns, the job belongs
        to someone else and it must not be marked done."""
        import threading
        import time as _t

        from app.db.session import owner_session
        from app.db.models import Job
        from app.jobs import handlers, queue, worker

        short_leases(job_max_runtime_seconds=1)
        monkeypatch.setitem(handlers.HANDLERS, "slow",
                            lambda s, p, hb: _t.sleep(4))
        with owner_session() as s:
            queue.enqueue(s, "slow", {})

        stop, stolen = threading.Event(), []
        thief = threading.Thread(target=_watch_for_theft, args=(stop, stolen))
        thief.start()
        try:
            assert worker.run(kinds=("slow",), once=True) == 0
        finally:
            stop.set(); thief.join()

        assert stolen == [2], "the hung job was never released"
        with owner_session() as s:
            job = s.query(Job).one()
            assert job.state == "running" and job.attempts == 2

    def test_a_handler_that_lost_its_job_stops_at_the_next_heartbeat(
            self, db, monkeypatch):
        from app.db.session import owner_session
        from app.db.models import Job
        from app.jobs import handlers, queue, worker

        wrote = []

        def taken_mid_run(session, payload, heartbeat):
            with owner_session() as other:
                other.execute(text("UPDATE jobs SET attempts = attempts + 1, "
                                   "leased_by = 'another-worker'"))
            heartbeat()
            wrote.append("result")

        monkeypatch.setitem(handlers.HANDLERS, "slow", taken_mid_run)
        with owner_session() as s:
            queue.enqueue(s, "slow", {})

        assert worker.run(kinds=("slow",), once=True) == 0
        assert wrote == [], "the handler wrote after losing its job"
        with owner_session() as s:
            job = s.query(Job).one()
            assert job.state == "running"
            assert job.leased_by == "another-worker"
