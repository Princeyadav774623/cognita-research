import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel

from auth import get_current_user_id
from billing import get_user_quota_status, apply_subscription_update
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/billing", tags=["Billing"])


class CheckoutRequest(BaseModel):
    success_url: str = "http://localhost:5173/?billing=success"
    cancel_url: str = "http://localhost:5173/?billing=cancel"


@router.get("/quota")
def get_quota(user_id: str = Depends(get_current_user_id)):
    """Check subscription tier and remaining search quota."""
    return get_user_quota_status(user_id)


@router.post("/create-checkout-session")
def create_checkout_session(body: CheckoutRequest, user_id: str = Depends(get_current_user_id)):
    """Create a Stripe checkout session for upgrading to Pro."""
    if not settings.stripe_secret_key:
        return {
            "checkout_url": f"{body.success_url}&demo_mode=true",
            "message": "Stripe API key not configured in environment — returning mock success redirect.",
        }

    try:
        import stripe
        stripe.api_key = settings.stripe_secret_key

        # A configured price id is preferred: it keeps pricing in the Stripe
        # dashboard rather than hardcoded here, where it can silently drift.
        if settings.stripe_price_id:
            line_items = [{"price": settings.stripe_price_id, "quantity": 1}]
        else:
            line_items = [{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Deep Research Pro Subscription"},
                    "unit_amount": 2000,  # $20.00 / month
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }]

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=line_items,
            # Echoed back on checkout.session.completed — this is how the
            # webhook attributes the payment to an application user.
            client_reference_id=user_id,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
        return {"checkout_url": session.url}
    except Exception as e:
        logger.error(f"[Billing] Stripe checkout error: {e}")
        raise HTTPException(status_code=500, detail="Failed to initialize checkout session")


def _period_end(raw) -> datetime | None:
    return datetime.fromtimestamp(raw, tz=timezone.utc) if raw else None


@router.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None, alias="Stripe-Signature")):
    """Stripe webhook receiver for handling subscription updates.

    The signature MUST be verified: this endpoint is unauthenticated and
    publicly reachable, so without verification anyone who knows the URL could
    POST a forged `checkout.session.completed` and upgrade themselves to Pro
    for free.
    """
    payload = await request.body()

    if not settings.stripe_webhook_secret:
        # Failing closed: an unverifiable event must never be allowed to
        # mutate subscription state.
        logger.error("[Billing] STRIPE_WEBHOOK_SECRET not configured — rejecting webhook")
        raise HTTPException(status_code=503, detail="Billing webhook not configured")

    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    try:
        import stripe
    except ImportError:
        logger.error("[Billing] stripe package not installed — cannot verify webhook")
        raise HTTPException(status_code=503, detail="Billing webhook not configured")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=settings.stripe_webhook_secret,
        )
    except ValueError:
        logger.warning("[Billing] Webhook rejected: malformed payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        logger.warning("[Billing] Webhook rejected: signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    obj = event["data"]["object"]
    logger.info(f"[Billing] Verified Stripe webhook event: {event_type}")

    if event_type == "checkout.session.completed":
        apply_subscription_update(
            user_id=obj.get("client_reference_id"),
            stripe_customer_id=obj.get("customer"),
            stripe_subscription_id=obj.get("subscription"),
            plan_tier="pro",
            status="active",
        )

    elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
        # Stripe statuses that should keep Pro access switched on.
        stripe_status = obj.get("status")
        active = stripe_status in ("active", "trialing")
        apply_subscription_update(
            user_id=None,
            stripe_customer_id=obj.get("customer"),
            stripe_subscription_id=obj.get("id"),
            plan_tier="pro" if active else "free",
            status="active" if active else ("past_due" if stripe_status == "past_due" else "canceled"),
            current_period_end=_period_end(obj.get("current_period_end")),
        )

    elif event_type == "customer.subscription.deleted":
        apply_subscription_update(
            user_id=None,
            stripe_customer_id=obj.get("customer"),
            stripe_subscription_id=obj.get("id"),
            plan_tier="free",
            status="canceled",
            current_period_end=_period_end(obj.get("current_period_end")),
        )

    else:
        logger.debug(f"[Billing] Ignoring unhandled event type: {event_type}")

    return {"status": "received"}
