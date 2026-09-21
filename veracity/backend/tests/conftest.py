import os
import subprocess
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/veracity_test")
os.environ.setdefault("DATABASE_URL_APP", "postgresql://localhost:5432/veracity_test")
os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")


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
        init()
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
