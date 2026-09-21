"""Request rate limiting.

The interesting cases are the ones where a limit silently stops limiting:
buckets that a client can mint at will, a per-path counter that gives every
media id its own allowance, and a storage error that takes the service down
instead of letting traffic through.
"""
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def clean(db):
    from app.db.session import owner_engine
    with owner_engine.begin() as c:
        c.execute(text("TRUNCATE rate_limits"))
    yield


class FakeRequest:
    """Enough of a Request for the limiter. Starlette's own is awkward to build
    and none of what it adds is under test here."""

    def __init__(self, method="GET", path="/api/media", auth=None, ip="1.2.3.4"):
        self.method = method
        self.headers = {"authorization": auth} if auth else {}
        self.url = type("U", (), {"path": path})()
        self.client = type("C", (), {"host": ip})()


class TestPricing:
    def test_starting_work_is_limited_harder_than_reading(self):
        """Priced by what a request costs us, not by how it is spelled."""
        from app.rate_limit import limit_for
        start = limit_for("POST", "/api/media")
        read = limit_for("GET", "/api/media")
        assert start.requests < read.requests

    def test_every_expensive_entry_point_is_covered(self):
        from app.rate_limit import CHEAP, limit_for
        for method, path in (("POST", "/api/media"),
                             ("POST", "/api/media/url"),
                             ("POST", "/api/media/abc/analysis")):
            assert limit_for(method, path).requests < CHEAP.requests, path

    def test_an_unlisted_route_gets_the_cheap_limit(self):
        from app.rate_limit import CHEAP, limit_for
        assert limit_for("GET", "/api/quota") == CHEAP


class TestCounting:
    def test_requests_are_allowed_up_to_the_limit_then_refused(self, db):
        from app.rate_limit import Limit, check
        limit = Limit(requests=3, window_seconds=60)
        results = [check("k1", limit)[0] for _ in range(5)]
        assert results == [True, True, True, False, False]

    def test_it_reports_how_long_until_the_window_ends(self, db):
        from app.rate_limit import Limit, check
        _, _, resets_in = check("k2", Limit(requests=1, window_seconds=60))
        assert 0 < resets_in <= 60

    def test_separate_buckets_do_not_share_a_count(self, db):
        from app.rate_limit import Limit, check
        limit = Limit(requests=1, window_seconds=60)
        assert check("a", limit)[0] is True
        assert check("b", limit)[0] is True


class TestIdentity:
    def test_two_callers_from_one_address_share_a_bucket(self):
        from app.rate_limit import identity
        assert identity(FakeRequest(ip="9.9.9.9")) == identity(
            FakeRequest(ip="9.9.9.9", path="/api/quota"))

    def test_different_addresses_get_different_buckets(self):
        from app.rate_limit import identity
        assert identity(FakeRequest(ip="1.1.1.1")) != identity(
            FakeRequest(ip="2.2.2.2"))

    def test_an_authenticated_caller_is_counted_by_token_not_address(self):
        """Otherwise a whole office behind one NAT shares one allowance."""
        from app.rate_limit import identity
        a = identity(FakeRequest(auth="Bearer aaa", ip="1.1.1.1"))
        b = identity(FakeRequest(auth="Bearer aaa", ip="2.2.2.2"))
        c = identity(FakeRequest(auth="Bearer bbb", ip="1.1.1.1"))
        assert a == b and a != c

    def test_the_raw_token_never_becomes_the_bucket_key(self):
        """The key is logged and stored; a bearer token in either is a
        credential leak."""
        from app.rate_limit import identity
        key = identity(FakeRequest(auth="Bearer supersecrettoken"))
        assert "supersecrettoken" not in key

    def test_a_forwarded_header_cannot_be_used_to_mint_buckets(self):
        """A client sets X-Forwarded-For itself and could rotate it forever,
        which would make the limit unenforceable."""
        from app.rate_limit import identity
        plain = FakeRequest(ip="5.5.5.5")
        spoofed = FakeRequest(ip="5.5.5.5")
        spoofed.headers["x-forwarded-for"] = "6.6.6.6"
        assert identity(plain) == identity(spoofed)


class TestBucketPaths:
    def test_ids_are_collapsed_so_each_item_is_not_its_own_allowance(self):
        """Without this, a client gets the full limit again for every media id
        it creates — which is unlimited."""
        from app.rate_limit import _bucket_path
        a = _bucket_path("/api/media/2b1c4e5a-1111-2222-3333-444455556666/ask")
        b = _bucket_path("/api/media/9f8e7d6c-9999-8888-7777-666655554444/ask")
        assert a == b == "/api/media/:id/ask"

    def test_ordinary_segments_are_left_alone(self):
        from app.rate_limit import _bucket_path
        assert _bucket_path("/api/media/url") == "/api/media/url"


class TestFailureBehaviour:
    @pytest.mark.asyncio
    async def test_a_storage_failure_lets_the_request_through(self, monkeypatch):
        """A limiter that takes the service down when its own table hiccups is
        worse than one that briefly lets traffic through."""
        import app.rate_limit as rl

        def explode(*_a, **_k):
            raise RuntimeError("database is having a moment")

        monkeypatch.setattr(rl, "check", explode)
        await rl.enforce(FakeRequest())      # must not raise

    @pytest.mark.asyncio
    async def test_being_over_the_limit_raises_429_with_retry_after(self, db):
        from fastapi import HTTPException

        import app.rate_limit as rl
        monkey = rl.Limit(requests=1, window_seconds=60)
        monkeypatched = lambda *_: monkey          # noqa: E731
        original = rl.limit_for
        rl.limit_for = monkeypatched
        try:
            req = FakeRequest(method="POST", path="/api/media", ip="7.7.7.7")
            await rl.enforce(req)
            with pytest.raises(HTTPException) as e:
                await rl.enforce(req)
        finally:
            rl.limit_for = original
        assert e.value.status_code == 429
        assert "Retry-After" in e.value.headers
        assert int(e.value.headers["Retry-After"]) > 0
