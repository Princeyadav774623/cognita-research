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
