from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

import jwt
from auth import verify_token


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
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=rate_limit_key)
