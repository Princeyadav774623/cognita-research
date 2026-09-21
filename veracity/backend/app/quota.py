"""Allowances, enforced atomically.

The naive check — read the counter, compare it, then write it back — is not a
limit. Two requests that read at the same time both see room and both proceed,
which is the failure mode that matters most because it shows up exactly when a
user is hammering the service. Every consume here is a single UPDATE whose WHERE
clause contains the limit, so the database decides and only one of two racing
requests can win.

Consumed on entry and refunded on failure. Charging on success instead would let
a user retry an expensive failing job indefinitely for free, and the job is what
costs money whether or not it produced anything.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AnalysisMode

log = logging.getLogger("quota")

PERIOD = timedelta(days=30)

# Analysis is priced in credits rather than runs, because the depths are not
# comparable: report searches for and judges every claim separately. These
# mirror the cost ratios the interface advertises.
CREDITS = {
    AnalysisMode.summary: 1,
    AnalysisMode.deep: 4,
    AnalysisMode.report: 15,
}


@dataclass(frozen=True)
class Tier:
    name: str
    transcription_minutes: float
    analysis_credits: int
    cost_usd: float


def _tiers() -> dict[str, Tier]:
    """Limits from the environment, with the production defaults inline.

    Read from config rather than hardcoded so a developer can be generous
    locally without that generosity being what ships. Editing the numbers in
    this file to get through an afternoon of testing is how a free tier ends up
    a hundred times larger than intended in production, and nobody notices until
    the bill.
    """
    cfg = settings()
    return {
        "free": Tier("free",
                     transcription_minutes=cfg.free_transcription_minutes,
                     analysis_credits=cfg.free_analysis_credits,
                     cost_usd=cfg.free_cost_usd),
        "pro": Tier("pro",
                    transcription_minutes=cfg.pro_transcription_minutes,
                    analysis_credits=cfg.pro_analysis_credits,
                    cost_usd=cfg.pro_cost_usd),
    }


TIERS = _tiers()


class QuotaExceeded(RuntimeError):
    """The user is out of allowance. Carries what ran out and when it resets."""

    def __init__(self, meter: str, used: float, limit: float,
                 resets_at: datetime):
        self.meter = meter
        self.used = used
        self.limit = limit
        self.resets_at = resets_at
        super().__init__(
            f"you have used {used:g} of {limit:g} {meter.replace('_', ' ')} "
            f"this period; it resets on {resets_at:%-d %B}"
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def tier_for(session: Session, user_id: str) -> Tier:
    row = session.execute(text(
        "SELECT tier FROM user_quotas WHERE user_id = :u"
    ), {"u": user_id}).first()
    return TIERS.get(row[0] if row else "free", TIERS["free"])


def _ensure(session: Session, user_id: str) -> None:
    session.execute(text("""
        INSERT INTO user_quotas (user_id, tier, period_start, updated_at)
        VALUES (:u, 'free', :now, :now)
        ON CONFLICT (user_id) DO NOTHING
    """), {"u": user_id, "now": _now()})


def consume(session: Session, user_id: str, *, meter: str,
            amount: float) -> None:
    """Take `amount` off `meter`, or raise QuotaExceeded.

    The period rolls inside the same statement that charges. Resetting first and
    charging second would let a request slip between the two and be charged
    against a period that no longer exists.
    """
    if amount <= 0:
        return
    if meter not in ("transcription_minutes", "analysis_credits", "cost_usd"):
        raise ValueError(f"unknown meter {meter!r}")

    _ensure(session, user_id)
    now = _now()
    cutoff = now - PERIOD

    limits = {t.name: getattr(t, meter) for t in TIERS.values()}
    row = session.execute(text(f"""
        UPDATE user_quotas SET
            period_start = CASE WHEN period_start < :cutoff
                                THEN :now ELSE period_start END,
            {meter}      = CASE WHEN period_start < :cutoff
                                THEN :amount ELSE {meter} + :amount END,
            updated_at   = :now
        WHERE user_id = :u
          AND (CASE WHEN period_start < :cutoff
                    THEN :amount ELSE {meter} + :amount END)
              <= CASE tier {' '.join(f"WHEN '{n}' THEN {v}" for n, v in limits.items())}
                 ELSE {TIERS['free'].__getattribute__(meter)} END
        RETURNING {meter}, period_start
    """), {"u": user_id, "now": now, "cutoff": cutoff, "amount": amount}).first()

    if row is None:
        # Nothing was written. Read back only to report the numbers.
        state = session.execute(text(f"""
            SELECT {meter}, tier, period_start FROM user_quotas WHERE user_id = :u
        """), {"u": user_id}).first()
        from app.observability import metrics
        metrics.count("veracity_quota_exceeded_total",
                      "Requests refused for want of allowance", meter=meter)
        tier = TIERS.get(state[1] if state else "free", TIERS["free"])
        raise QuotaExceeded(meter, float(state[0]) if state else 0.0,
                            getattr(tier, meter),
                            (state[2] if state else now) + PERIOD)


def refund(session: Session, user_id: str, *, meter: str,
           amount: float) -> None:
    """Give back allowance for work that did not happen.

    Clamped at zero: a refund for a job whose charge fell in the previous period
    would otherwise hand the user free allowance in this one.
    """
    if amount <= 0:
        return
    session.execute(text(f"""
        UPDATE user_quotas
        SET {meter} = GREATEST(0, {meter} - :amount), updated_at = :now
        WHERE user_id = :u
    """), {"u": user_id, "amount": amount, "now": _now()})
    log.info("[quota] refunded %g %s to %s", amount, meter, user_id)


def snapshot(session: Session, user_id: str) -> dict:
    """What the interface shows. Never raises."""
    _ensure(session, user_id)
    row = session.execute(text("""
        SELECT tier, period_start, transcription_minutes, analysis_credits, cost_usd
        FROM user_quotas WHERE user_id = :u
    """), {"u": user_id}).first()

    tier = TIERS.get(row[0], TIERS["free"])
    started = row[1]
    # Report a rolled-over period as empty rather than showing last period's
    # numbers until something happens to trigger the reset.
    rolled = started < _now() - PERIOD
    used = (0.0, 0, 0.0) if rolled else (row[2], row[3], row[4])

    return {
        "tier": tier.name,
        "period_start": (_now() if rolled else started),
        "resets_at": (_now() if rolled else started) + PERIOD,
        "transcription_minutes": {"used": round(used[0], 2),
                                  "limit": tier.transcription_minutes},
        "analysis_credits": {"used": int(used[1]),
                             "limit": tier.analysis_credits},
        "cost_usd": {"used": round(used[2], 4), "limit": tier.cost_usd},
        "credits_per_mode": {m.value: c for m, c in CREDITS.items()},
    }
