"""Allowances.

The property that makes a quota a limit rather than a suggestion is that it
holds under concurrency. Everything else here is arithmetic; the race test is
the one that would have caught the read-compare-write version.
"""
import threading
from datetime import timedelta

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def clean(db):
    from app.db.session import owner_engine
    with owner_engine.begin() as c:
        c.execute(text("TRUNCATE user_quotas"))
    yield


def used(user, meter):
    from app.db.session import app_session
    from app.quota import snapshot
    with app_session(user) as s:
        return snapshot(s, user)[meter]["used"]


def spend(user, meter, amount):
    from app.db.session import app_session
    from app.quota import consume
    with app_session(user) as s:
        consume(s, user, meter=meter, amount=amount)


class TestConsuming:
    def test_a_first_charge_creates_the_row(self, db):
        spend("q1", "analysis_credits", 3)
        assert used("q1", "analysis_credits") == 3

    def test_charges_accumulate(self, db):
        spend("q2", "analysis_credits", 3)
        spend("q2", "analysis_credits", 4)
        assert used("q2", "analysis_credits") == 7

    def test_going_over_raises_and_writes_nothing(self, db):
        """A refused charge must not be partially applied — the user would be
        billed for work that never ran."""
        from app.quota import QuotaExceeded, TIERS
        limit = TIERS["free"].analysis_credits
        spend("q3", "analysis_credits", limit - 1)
        with pytest.raises(QuotaExceeded):
            spend("q3", "analysis_credits", 5)
        assert used("q3", "analysis_credits") == limit - 1

    def test_the_error_says_what_ran_out_and_when_it_resets(self, db):
        from app.quota import QuotaExceeded, TIERS
        spend("q4", "analysis_credits", TIERS["free"].analysis_credits)
        with pytest.raises(QuotaExceeded) as e:
            spend("q4", "analysis_credits", 1)
        assert e.value.meter == "analysis_credits"
        assert "resets on" in str(e.value)

    def test_the_meters_are_independent(self, db):
        """Transcription length and analysis depth are unrelated costs. Draining
        one must not block the other."""
        from app.quota import TIERS
        spend("q5", "analysis_credits", TIERS["free"].analysis_credits)
        spend("q5", "transcription_minutes", 5)
        assert used("q5", "transcription_minutes") == 5

    def test_a_zero_or_negative_charge_is_a_no_op(self, db):
        spend("q6", "analysis_credits", 0)
        spend("q6", "analysis_credits", -5)
        assert used("q6", "analysis_credits") == 0

    def test_an_unknown_meter_is_refused(self, db):
        from app.db.session import app_session
        from app.quota import consume
        with pytest.raises(ValueError, match="unknown meter"):
            with app_session("q7") as s:
                consume(s, "q7", meter="wishes", amount=1)


class TestConcurrency:
    def test_ten_racing_charges_cannot_overspend(self, db):
        """Read-compare-write is not a limit: two requests that read together
        both see room and both proceed. This is the test that catches it."""
        from app.db.session import app_session
        from app.quota import QuotaExceeded, TIERS, consume

        limit = TIERS["free"].analysis_credits
        spend("race", "analysis_credits", limit - 1)   # one credit left

        won = []
        lock = threading.Lock()
        barrier = threading.Barrier(10)

        def attempt():
            barrier.wait()
            try:
                with app_session("race") as s:
                    consume(s, "race", meter="analysis_credits", amount=1)
                with lock:
                    won.append(1)
            except QuotaExceeded:
                pass

        threads = [threading.Thread(target=attempt) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert len(won) == 1, f"{len(won)} requests got the last credit"
        assert used("race", "analysis_credits") == limit


class TestRefunds:
    def test_a_refund_returns_allowance(self, db):
        spend("r1", "analysis_credits", 10)
        from app.db.session import app_session
        from app.quota import refund
        with app_session("r1") as s:
            refund(s, "r1", meter="analysis_credits", amount=4)
        assert used("r1", "analysis_credits") == 6

    def test_a_refund_cannot_go_below_zero(self, db):
        """A refund for a charge that fell in a previous period would otherwise
        mint free allowance in this one."""
        from app.db.session import app_session
        from app.quota import refund
        spend("r2", "analysis_credits", 2)
        with app_session("r2") as s:
            refund(s, "r2", meter="analysis_credits", amount=50)
        assert used("r2", "analysis_credits") == 0


class TestPeriods:
    def test_a_stale_period_resets_on_the_next_charge(self, db):
        """The roll happens inside the charging statement. Resetting first and
        charging second would let a request be charged to a period that no
        longer exists."""
        from app.db.session import owner_engine
        from app.quota import PERIOD, _now

        spend("p1", "analysis_credits", 50)
        with owner_engine.begin() as c:
            c.execute(text(
                "UPDATE user_quotas SET period_start = :old WHERE user_id = 'p1'"
            ), {"old": _now() - PERIOD - timedelta(days=1)})

        spend("p1", "analysis_credits", 3)
        assert used("p1", "analysis_credits") == 3, "the old period was carried over"

    def test_a_rolled_period_reads_as_empty_before_anything_is_charged(self, db):
        """Otherwise the interface shows last period's numbers until the user
        happens to do something that triggers the reset."""
        from app.db.session import owner_engine
        from app.quota import PERIOD, _now

        spend("p2", "analysis_credits", 50)
        with owner_engine.begin() as c:
            c.execute(text(
                "UPDATE user_quotas SET period_start = :old WHERE user_id = 'p2'"
            ), {"old": _now() - PERIOD - timedelta(days=1)})
        assert used("p2", "analysis_credits") == 0


class TestSnapshot:
    def test_it_never_raises_on_an_exhausted_allowance(self, db):
        """This is what the interface calls to decide what to offer. Refusing to
        report a spent quota hides the state the user most needs to see."""
        from app.db.session import app_session
        from app.quota import TIERS, snapshot
        spend("s1", "analysis_credits", TIERS["free"].analysis_credits)
        with app_session("s1") as s:
            snap = snapshot(s, "s1")
        assert snap["analysis_credits"]["used"] == TIERS["free"].analysis_credits

    def test_it_reports_what_each_depth_costs(self, db):
        from app.db.session import app_session
        from app.quota import snapshot
        with app_session("s2") as s:
            modes = snapshot(s, "s2")["credits_per_mode"]
        assert modes["report"] > modes["deep"] > modes["summary"]
