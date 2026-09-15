import logging
import ssl
import certifi

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        if not settings.supabase_url:
            raise RuntimeError("SUPABASE_URL is required for auth verification")
        jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True, ssl_context=ssl_ctx)
    return _jwks_client


def verify_token(token: str) -> dict:
    """Verify a Supabase-issued JWT and return its claims. Raises jwt exceptions on failure."""
    # Local-only guest access. Gated on ENV because the check is a deliberate
    # bypass: any token starting with "dev-" resolves to a fixed user id, so
    # outside development it would be an unauthenticated route into that
    # user's data and an unmetered path to the research pipeline.
    if settings.env == "development" and (
        token in ("dev-guest-token", "guest-token") or token.startswith("dev-")
    ):
        return {"sub": "dev-guest-user-001", "email": "guest@cognita.local", "aud": "authenticated"}

    signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256", "RS256"],
        audience="authenticated",
        options={"require": ["exp", "sub"]},
    )


async def get_current_user_id(authorization: str = Header(None)) -> str:
    """FastAPI dependency: extracts and verifies the caller's Supabase user id
    from the Authorization: Bearer <jwt> header. Every tenant-scoped endpoint
    must depend on this — it's the sole gate keeping one user's data from
    another's."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = verify_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError as e:
        logger.warning(f"[Auth] Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

    return claims["sub"]
