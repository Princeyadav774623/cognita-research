import logging
from typing import Optional
from pydantic import BaseModel
from config import get_settings
from db import tenant_session, Base
from sqlalchemy import Column, String, Integer, DateTime
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
settings = get_settings()

FREE_QUOTA_PER_MONTH = 10


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    user_id = Column(String, primary_key=True)
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True)
    plan_tier = Column(String, default="free")  # "free" | "pro"
    status = Column(String, default="active")   # "active" | "canceled" | "past_due"
    monthly_queries_used = Column(Integer, default=0)
    current_period_end = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


def get_user_quota_status(user_id: str) -> dict:
    """Retrieve the subscription status and remaining query balance for a user."""
    with tenant_session(user_id) as db:
        sub = db.query(UserSubscription).filter(UserSubscription.user_id == user_id).first()
        if not sub:
            # Create default free tier
            sub = UserSubscription(user_id=user_id, plan_tier="free", monthly_queries_used=0)
            db.add(sub)
            db.commit()
            db.refresh(sub)

        is_pro = sub.plan_tier == "pro" and sub.status == "active"
        quota_limit = 999999 if is_pro else FREE_QUOTA_PER_MONTH
        remaining = max(0, quota_limit - sub.monthly_queries_used)

        return {
            "user_id": user_id,
            "plan_tier": sub.plan_tier,
            "status": sub.status,
            "queries_used": sub.monthly_queries_used,
            "quota_limit": quota_limit,
            "remaining_queries": remaining,
            "has_quota": remaining > 0 or is_pro,
        }


def increment_user_usage(user_id: str) -> None:
    """Increment monthly query counter for the user."""
    with tenant_session(user_id) as db:
        sub = db.query(UserSubscription).filter(UserSubscription.user_id == user_id).first()
        if sub:
            sub.monthly_queries_used += 1
            db.commit()
