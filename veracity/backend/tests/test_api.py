"""The HTTP surface.

Two things are worth testing here beyond "does it return 200": that one tenant's
id is useless to another, and that the guard rails on upload and URL submission
actually hold. The rest is plumbing.
"""
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.db


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("ALLOW_GUEST", "true")
    from app.main import app
    from app.db.session import owner_engine
    with owner_engine.begin() as c:
        c.execute(text("TRUNCATE jobs, media_items CASCADE"))
    # lifespan is skipped: the db fixture has already bootstrapped the schema.
    return TestClient(app)


def _as(user: str) -> dict:
    """Headers that make the request a given tenant, without a real Supabase."""
    return {"X-Test-User": user}


class TestHealth:
    def test_reports_isolation_and_configuration(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["database"] == "ok"
        assert body["tenant_isolation"] == "enforced"
        assert body["asr_backend"] in ("groq", "faster-whisper")


class TestUpload:
    def test_a_file_is_accepted_and_queued(self, client, tone_media):
        from app.db.session import owner_session
        from app.jobs import queue

        with open(tone_media, "rb") as fh:
            r = client.post("/api/media",
                            files={"file": ("clip.mp4", fh, "video/mp4")})
        assert r.status_code == 202
        body = r.json()
        assert body["state"] == "pending"
        assert body["filename"] == "clip.mp4"

        with owner_session() as s:
            assert queue.stats(s)["queued"] == 1

    def test_an_empty_file_is_refused_and_leaves_no_row(self, client):
        r = client.post("/api/media",
                        files={"file": ("empty.mp4", io.BytesIO(b""), "video/mp4")})
        assert r.status_code == 400
        assert "empty" in r.json()["detail"]
        assert client.get("/api/media").json()["total"] == 0

    def test_an_oversized_upload_is_refused_mid_stream(self, client, monkeypatch):
        """The cap is enforced against bytes actually seen, not against
        Content-Length, which the client controls and can simply understate."""
        import dataclasses

        import app.api.routes_media as rm
        small = dataclasses.replace(rm.settings(), max_upload_bytes=1024 * 1024)
        monkeypatch.setattr(rm, "settings", lambda: small)

        payload = io.BytesIO(b"\0" * (4 * 1024 * 1024))
        r = client.post("/api/media",
                        files={"file": ("big.mp4", payload, "video/mp4")})
        assert r.status_code == 413
        assert "limit" in r.json()["detail"]
        # The half-written file and its row are both gone.
        assert client.get("/api/media").json()["total"] == 0


class TestIsolation:
    def test_another_tenants_media_id_is_a_404(self, client, tone_media, db):
        """Not a 403. Distinguishing "not yours" from "does not exist" confirms
        an id to someone who cannot see the row."""
        from app.db.session import app_session
        from app.db.models import MediaItem
        with app_session("someone-else") as s:
            m = MediaItem(user_id="someone-else", source_kind="upload",
                          original_filename="theirs.mp4")
            s.add(m); s.flush()
            other_id = m.id

        assert client.get(f"/api/media/{other_id}").status_code == 404
        assert client.get(f"/api/media/{other_id}/transcript").status_code == 404
        assert client.delete(f"/api/media/{other_id}").status_code == 404

    def test_listing_shows_only_your_own(self, client, db):
        from app.db.session import app_session
        from app.db.models import MediaItem
        with app_session("someone-else") as s:
            s.add(MediaItem(user_id="someone-else", source_kind="upload",
                            original_filename="theirs.mp4"))
        assert client.get("/api/media").json()["total"] == 0


class TestTranscript:
    def test_transcript_before_ready_is_a_409_not_an_empty_list(self, client, db):
        """An empty transcript and a transcript that does not exist yet are
        different things, and a 200 with [] conflates them."""
        from app.db.session import app_session
        from app.db.models import MediaItem, MediaState
        with app_session("guest-local") as s:
            m = MediaItem(user_id="guest-local", source_kind="upload",
                          original_filename="x.mp4", state=MediaState.transcribing)
            s.add(m); s.flush()
            mid = m.id
        r = client.get(f"/api/media/{mid}/transcript")
        assert r.status_code == 409
        assert "transcribing" in r.json()["detail"]


class TestUrlSubmission:
    def test_disabled_by_default(self, client):
        r = client.post("/api/media/url",
                        json={"url": "https://example.com/video"})
        assert r.status_code == 501
        assert "upload the file instead" in r.json()["detail"]

    def test_a_non_http_scheme_is_rejected(self, client):
        r = client.post("/api/media/url", json={"url": "file:///etc/passwd"})
        assert r.status_code == 422


class TestSsrfGuard:
    @pytest.mark.parametrize("url", [
        "http://localhost:5432/",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
    ])
    def test_urls_pointing_inside_the_perimeter_are_refused(self, url):
        """Without this, "paste a link" is a server-side request forgery
        primitive: the service fetches an internal address and returns what it
        found."""
        from app.ingest.resolve import ResolveError, check_url_is_fetchable
        with pytest.raises(ResolveError, match="private address|no host"):
            check_url_is_fetchable(url)

    def test_a_public_url_passes_the_guard(self):
        from app.ingest.resolve import check_url_is_fetchable
        check_url_is_fetchable("https://example.com/watch?v=abc")


class TestEventLoop:
    """Blocking work must never run on the event loop.

    The whole API process serves every request from one loop. A route declared
    `async` that then makes a synchronous database call, runs ffprobe, or waits
    on a model holds that loop, and every other user on the process waits with
    it — for as long as a model call with retries takes, which is minutes.
    """

    def test_no_route_or_auth_dependency_is_async(self):
        """Every route here does I/O through synchronous libraries, so none may
        be a coroutine. A new one that is will fail this until it is not."""
        import inspect

        from fastapi.routing import APIRoute

        from app.api.auth import current_principal
        from app.main import app

        offenders = [r.path for r in app.routes
                     if isinstance(r, APIRoute)
                     and inspect.iscoroutinefunction(r.endpoint)]
        assert offenders == []
        assert not inspect.iscoroutinefunction(current_principal)

    def test_a_slow_question_does_not_stall_other_requests(self, client,
                                                           monkeypatch):
        """Timed from when both requests start. Were /ask on the event loop, the
        quota request could not even begin until the model call returned."""
        import asyncio
        import time

        import httpx

        from app.db.models import MediaItem, MediaState
        from app.db.session import app_session
        from app.main import app

        with app_session("guest-local") as s:
            m = MediaItem(user_id="guest-local", source_kind="upload",
                          original_filename="talk.mp4", state=MediaState.ready)
            s.add(m); s.flush()
            media_id = m.id

        def slow_model(*_a, **_k):
            time.sleep(1.5)
            return {"answered": True, "answer": "It is large.", "used": [0]}

        monkeypatch.setattr("app.api.routes_ask.complete_json", slow_model)
        monkeypatch.setattr(
            "app.analysis.retrieve.retrieve",
            lambda *_a, **_k: [{"start_ms": 0, "end_ms": 1000,
                                "text": "the reef is large"}])

        async def scenario():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as c:
                started = time.monotonic()
                ask = asyncio.create_task(c.post(
                    f"/api/media/{media_id}/ask",
                    json={"question": "how big is the reef?"}))
                await asyncio.sleep(0.3)
                quota = await c.get("/api/quota")
                quota_at = time.monotonic() - started
                answer = await ask
            return quota, quota_at, answer

        quota, quota_at, answer = asyncio.run(scenario())
        assert quota.status_code == 200
        assert answer.status_code == 200 and answer.json()["answered"] is True
        assert quota_at < 1.0, (
            f"the quota request waited {quota_at:.2f}s behind a slow question")
