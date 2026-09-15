import logging
from db import tenant_session, SessionLocal, Base, engine
from sqlalchemy import Column, String, Integer, DateTime, text
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

FREE_QUOTA_PER_MONTH = 10
PRO_QUOTA_PER_MONTH = 999999


class QuotaExceededError(Exception):
    """Raised when a user has consumed their monthly query allowance."""

    def __init__(self, status: dict):
        self.status = status
        super().__init__(
            f"Monthly quota exhausted ({status['queries_used']}/{status['quota_limit']} used)"
        )


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    user_id = Column(String, primary_key=True)
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True)
    plan_tier = Column(String, default="free")  # "free" | "pro"
    status = Column(String, default="active")   # "active" | "canceled" | "past_due"
    monthly_queries_used = Column(Integer, default=0)
    # Start of the billing period the counter above is measured against.
    # Without this the "monthly" quota never resets and a free user is locked
    # out permanently after their first 10 queries.
    usage_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


def init_billing_db() -> None:
    """Retained as a no-op call site. The schema this used to patch by hand is
    owned by Alembic now (see db.init_db)."""
    return None


def _same_billing_period(period_start: datetime | None, now: datetime) -> bool:
    """Usage counters roll over at the start of each calendar month."""
    if period_start is None:
        return False
    if period_start.tzinfo is None:
        period_start = period_start.replace(tzinfo=timezone.utc)
    return (period_start.year, period_start.month) == (now.year, now.month)


def _get_or_create(db, user_id: str) -> UserSubscription:
    """Fetch the user's subscription row, creating a free-tier one on first
    sight, and roll the usage counter over if we've crossed into a new month."""
    now = datetime.now(timezone.utc)
    sub = db.query(UserSubscription).filter(UserSubscription.user_id == user_id).first()

    if not sub:
        sub = UserSubscription(
            user_id=user_id,
            plan_tier="free",
            status="active",
            monthly_queries_used=0,
            usage_period_start=now,
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
        return sub

    if not _same_billing_period(sub.usage_period_start, now):
        sub.monthly_queries_used = 0
        sub.usage_period_start = now
        db.commit()
        db.refresh(sub)

    return sub


def _status_dict(sub: UserSubscription) -> dict:
    is_pro = sub.plan_tier == "pro" and sub.status == "active"
    quota_limit = PRO_QUOTA_PER_MONTH if is_pro else FREE_QUOTA_PER_MONTH
    used = sub.monthly_queries_used or 0
    remaining = max(0, quota_limit - used)

    return {
        "user_id": sub.user_id,
        "plan_tier": sub.plan_tier,
        "status": sub.status,
        "queries_used": used,
        "quota_limit": quota_limit,
        "remaining_queries": remaining,
        "has_quota": remaining > 0,
        "period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
    }


def get_user_quota_status(user_id: str) -> dict:
    """Retrieve the subscription status and remaining query balance for a user."""
    with tenant_session(user_id) as db:
        return _status_dict(_get_or_create(db, user_id))


def consume_quota(user_id: str) -> dict:
    """Atomically check and consume one query of the user's monthly allowance.

    Reserving up front (rather than incrementing after the pipeline finishes)
    means a user can't fire off unlimited concurrent requests that all pass
    the check before any of them increments the counter.

    Raises QuotaExceededError if no allowance remains.
    """
    with tenant_session(user_id) as db:
        sub = _get_or_create(db, user_id)
        status = _status_dict(sub)

        if not status["has_quota"]:
            raise QuotaExceededError(status)

        sub.monthly_queries_used = (sub.monthly_queries_used or 0) + 1
        # Build the return value from in-memory state before committing, and do
        # not re-read afterwards. A refresh() after commit is a second query on
        # a fresh connection, and anything that goes wrong there raises *after*
        # the increment is already durable — so the caller never learns the
        # query was reserved, never triggers the refund, and the user silently
        # loses an allowance they did not spend.
        reserved = _status_dict(sub)
        db.commit()
        return reserved


def refund_quota(user_id: str) -> None:
    """Give back a reserved query when the pipeline failed, so a server-side
    error doesn't silently burn the user's allowance."""
    with tenant_session(user_id) as db:
        sub = db.query(UserSubscription).filter(UserSubscription.user_id == user_id).first()
        if sub and (sub.monthly_queries_used or 0) > 0:
            sub.monthly_queries_used -= 1
            db.commit()


def apply_subscription_update(
    user_id: str | None,
    stripe_customer_id: str | None,
    stripe_subscription_id: str | None = None,
    plan_tier: str | None = None,
    status: str | None = None,
    current_period_end: datetime | None = None,
) -> bool:
    """Apply a Stripe-driven subscription change.

    Runs on the owner engine rather than tenant_session: Stripe webhooks carry
    no user JWT, and resolving a customer id to a row requires reading across
    tenants, which RLS deliberately forbids for the runtime role.

    Returns True if a row was updated/created.
    """
    db = SessionLocal()
    try:
        sub = None
        if user_id:
            sub = db.query(UserSubscription).filter(UserSubscription.user_id == user_id).first()
        if sub is None and stripe_customer_id:
            sub = (
                db.query(UserSubscription)
                .filter(UserSubscription.stripe_customer_id == stripe_customer_id)
                .first()
            )

        if sub is None:
            if not user_id:
                logger.warning(
                    "[Billing] Webhook event for unknown customer %s and no client_reference_id "
                    "— cannot attribute to a user", stripe_customer_id,
                )
                return False
            sub = UserSubscription(user_id=user_id, usage_period_start=datetime.now(timezone.utc))
            db.add(sub)

        if stripe_customer_id:
            sub.stripe_customer_id = stripe_customer_id
        if stripe_subscription_id:
            sub.stripe_subscription_id = stripe_subscription_id
        if plan_tier:
            sub.plan_tier = plan_tier
        if status:
            sub.status = status
        if current_period_end:
            sub.current_period_end = current_period_end

        db.commit()
        logger.info(
            "[Billing] Subscription updated for user=%s tier=%s status=%s",
            sub.user_id, sub.plan_tier, sub.status,
        )
        return True
    finally:
        db.close()
