import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from auth import get_current_user_id
from billing import get_user_quota_status, UserSubscription
from db import SessionLocal
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
    # Scaffolded integration: If STRIPE_SECRET_KEY is configured, call stripe SDK
    stripe_key = getattr(settings, "stripe_secret_key", None)
    if not stripe_key:
        return {
            "checkout_url": f"{body.success_url}&demo_mode=true",
            "message": "Stripe API key not configured in environment — returning mock success redirect.",
        }

    try:
        import stripe
        stripe.api_key = stripe_key
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Deep Research Pro Subscription"},
                    "unit_amount": 2000,  # $20.00 / month
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            mode="subscription",
            client_reference_id=user_id,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
        return {"checkout_url": session.url}
    except Exception as e:
        logger.error(f"[Billing] Stripe checkout error: {e}")
        raise HTTPException(status_code=500, detail="Failed to initialize checkout session")


@router.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None, alias="Stripe-Signature")):
    """Stripe webhook receiver for handling subscription updates."""
    payload = await request.body()
    logger.info("[Billing] Received Stripe webhook event")
    return {"status": "received"}
