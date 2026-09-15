from fastapi import Request
from slowapi import Limiter
from rate_limit_middleware import client_ip

import logging

import jwt
from auth import verify_token
from config import get_settings


def rate_limit_key(request: Request) -> str:
    """Rate-limit per authenticated user when possible, so one user can't
    exhaust another's quota and IP-sharing (VPNs, corporate NAT) doesn't
    cause false throttling. Falls back to IP for unauthenticated requests.

    slowapi's key_func only gets the raw Request (dependency injection
    hasn't run yet at this point), so the token is parsed directly here —
    duplicating the verification `get_current_user_id` does, but that's the
    cost of the key needing to exist before FastAPI resolves dependencies.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
        try:
            claims = verify_token(token)
            return f"user:{claims['sub']}"
        except jwt.PyJWTError:
            pass
    return f"ip:{client_ip(request)}"


_settings = get_settings()

if _settings.rate_limit_storage_uri:
    limiter = Limiter(key_func=rate_limit_key, storage_uri=_settings.rate_limit_storage_uri)
else:
    # Single-instance default. Loud rather than silent, because the failure
    # mode when it is wrong is a limit that quietly does not hold.
    if _settings.env != "development":
        logging.getLogger(__name__).warning(
            "[RateLimit] Using in-process storage. Counters are per-instance, so "
            "running more than one process multiplies every limit. Set "
            "RATE_LIMIT_STORAGE_URI to a redis:// URL before scaling out."
        )
    limiter = Limiter(key_func=rate_limit_key)
