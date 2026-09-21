import os
import subprocess
import pytest

# Point at the test database BEFORE app.config is imported anywhere, and
# override rather than setdefault: a developer's .env is normally exported into
# the shell, and setdefault would then quietly hand the suite the development
# database. The teardown truncates, so that costs you your work — which is
# exactly what happened once before this guard existed.
_USER = os.environ.get("USER", "postgres")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", f"postgresql://{_USER}@localhost:5432/veracity_test")
os.environ["DATABASE_URL_APP"] = os.environ.get(
    "TEST_DATABASE_URL_APP",
    "postgresql://veracity_app:veracity_local@localhost:5432/veracity_test")
os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
os.environ.setdefault("MEDIA_ROOT", "/tmp/veracity-test-media")
# Set here rather than in a fixture: Settings is an lru_cached frozen dataclass
# built on first import, so monkeypatching the environment inside a test is too
# late and silently has no effect.
os.environ["ALLOW_GUEST"] = "true"
os.environ["ALLOW_REMOTE_FETCH"] = "false"

if not os.environ["DATABASE_URL"].rstrip("/").endswith("_test"):
    raise RuntimeError(
        "refusing to run: the test database name must end in '_test'. "
        f"Got {os.environ['DATABASE_URL']!r}. The suite truncates tables."
    )


@pytest.fixture(scope="session")
def tone_media(tmp_path_factory):
    """A short A/V file with a real audio track."""
    d = tmp_path_factory.mktemp("media")
    out = d / "tone.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        "-shortest", str(out),
    ], capture_output=True, check=True)
    return str(out)


@pytest.fixture(scope="session")
def silent_media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    out = d / "silent.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5:duration=2",
        "-an", str(out),
    ], capture_output=True, check=True)
    return str(out)


def pytest_configure(config):
    config.addinivalue_line("markers", "db: needs a live Postgres")


@pytest.fixture(scope="session")
def db():
    """Bring a real database up, or skip. These tests are worthless mocked."""
    try:
        from app.db.bootstrap import init
        from app.db.models import Base
        from app.db.session import owner_engine
        # create_all rather than migrating: the suite wants the schema the code
        # declares right now, not the history of how it got there. Whether the
        # migrations actually produce that schema is its own test.
        Base.metadata.create_all(owner_engine)
        init(run_migrations=False)
    except Exception as exc:                      # pragma: no cover
        pytest.skip(f"no database: {exc}")
    yield
    from app.db.session import owner_engine
    from sqlalchemy import text
    with owner_engine.begin() as c:
        c.execute(text("TRUNCATE media_items, analyses, jobs CASCADE"))


@pytest.fixture
def alice():
    return "user-alice"


@pytest.fixture
def bob():
    return "user-bob"


@pytest.fixture
def alice_media(db, alice):
    from app.db.session import app_session
    from app.db.models import MediaItem, TranscriptChunk
    with app_session(alice) as s:
        m = MediaItem(user_id=alice, source_kind="upload",
                      original_filename="alice.mp4")
        s.add(m)
        s.flush()
        s.add(TranscriptChunk(media_id=m.id, ordinal=0, start_ms=0,
                              end_ms=1000, text="hello", confidence=0.9))
        s.flush()
        media_id = m.id
    yield media_id
    from app.db.session import owner_session
    with owner_session() as s:
        s.query(MediaItem).filter_by(id=media_id).delete()


@pytest.fixture
def stub_asr(monkeypatch):
    """Transcription that does not leave the machine.

    The worker tests are about the pipeline — state transitions, persistence,
    redelivery — not about the accuracy of a vendor's model. Depending on a
    live paid API made them slow, non-deterministic, and silently green only
    while someone's key happened to be exported into the shell.

    The real transcribers are exercised by hand against real audio; what is
    checked here is that whatever they return is shifted, stored and chunked
    correctly.
    """
    from app.ingest.transcribe import Segment, Transcript, Word

    class StubTranscriber:
        name = "stub"
        model = "stub-v1"

        def transcribe(self, path, *, language=None):
            # Deliberately starts at zero: the offset shifting in
            # transcribe_parts is the thing under test, so a stub that already
            # knew its position would hide a bug there.
            words = [Word("the", 0, 300, 0.9, True),
                     Word("reef", 300, 800, 0.9, True)]
            return Transcript(
                segments=[Segment(start_ms=0, end_ms=800,
                                  text="the reef", confidence=0.9,
                                  words=words)],
                language="en", backend="stub", model="stub-v1",
            )

    monkeypatch.setattr("app.ingest.transcribe.get_transcriber",
                        lambda: StubTranscriber())
    return StubTranscriber()
