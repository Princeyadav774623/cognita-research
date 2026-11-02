"""What the caller has left."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth import Principal, current_principal
from app.db.session import app_session
from app.quota import snapshot

router = APIRouter(prefix="/api/quota", tags=["quota"])


@router.get("")
def get_quota(principal: Principal = Depends(current_principal)):
    """Deliberately never raises on an exhausted allowance.

    This is the endpoint the interface calls to decide what to offer. Refusing
    to report a quota because the quota is spent would hide exactly the state
    the user needs to see.
    """
    with app_session(principal.user_id) as session:
        return snapshot(session, principal.user_id)
