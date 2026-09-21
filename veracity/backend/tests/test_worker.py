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


def _queue_media(user: str, source_path: str):
    from app.db.session import app_session, owner_session
    from app.db.models import MediaItem, MediaState
    from app.jobs import queue
    with app_session(user) as s:
        m = MediaItem(user_id=user, source_kind="upload",
                      original_filename=os.path.basename(source_path),
                      source_path=source_path, state=MediaState.pending)
        s.add(m); s.flush()
        media_id = m.id
    with owner_session() as s:
        queue.enqueue(s, "ingest", {"media_id": media_id})
    return media_id


class TestIngestJob:
    def test_media_reaches_ready_with_timed_chunks(self, db, tone_media):
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

        media_id = _queue_media("user-w2", "/nonexistent/gone.mp4")
        worker.run(kinds=("ingest",), once=True)

        with app_session("user-w2") as s:
            m = s.get(MediaItem, media_id)
            assert m.state == MediaState.failed
            assert "source file is missing" in m.error

        with owner_session() as s:
            job = s.query(Job).first()
            # Retried rather than abandoned: a missing file is usually a race
            # with an upload still being written, not a permanent condition.
            assert job.state == "queued"
            assert job.attempts == 1
            assert "missing" in job.last_error

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

    def test_redelivery_of_a_finished_item_is_a_no_op(self, db, tone_media):
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
