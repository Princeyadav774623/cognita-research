"""Who is asking.

Identity is delegated: tokens are issued by Supabase and verified here against
its public JWKS, so this service holds no auth secret and a leak of its
environment cannot mint a valid token.

Guest mode exists for local development and is off unless `ALLOW_GUEST=true`.
It is a real risk worth naming: switched on in production it would make every
request the same user, and with a single tenant id row-level security stops
separating anything. Startup logs a warning for that reason.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app.config import settings

log = logging.getLogger("auth")

_jwks_client = None


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str | None = None
    is_guest: bool = False


def _jwks():
    global _jwks_client
    if _jwks_client is None:
        import jwt
        url = settings().supabase_jwks_url
        if not url:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "authentication is not configured on this server",
            )
        # Caches keys and refetches on an unknown kid, so a key rotation does
        # not need a restart.
        _jwks_client = jwt.PyJWKClient(url, cache_keys=True)
    return _jwks_client


def _decode(token: str) -> dict:
    """Verify a token and return its claims.

    Two ways to be configured, and the choice is about who issues tokens:

      asymmetric  Supabase signs, we verify against its published JWKS. We hold
                  no secret, so a leak of this service's environment cannot mint
                  a token. This is what production should use.
      symmetric   A shared HS256 secret, for a deployment with no Supabase. The
                  secret both signs and verifies, so anything able to read the
                  environment can issue a token for any user.

    Algorithms are pinned per mode and never taken from the token's own header.
    A verifier that trusts `alg` accepts a token that says `alg: none`, or one
    signed with HS256 using the public RSA key as the shared secret — the two
    classic JWT forgeries, both of which are the verifier's fault.
    """
    import jwt

    secret = settings().jwt_secret
    if secret:
        return jwt.decode(
            token, secret, algorithms=["HS256"],
            audience=settings().supabase_audience,
            options={"require": ["exp", "sub"], "verify_exp": True},
        )
    key = _jwks().get_signing_key_from_jwt(token).key
    return jwt.decode(
        token, key, algorithms=["RS256", "ES256"],
        audience=settings().supabase_audience,
        options={"require": ["exp", "sub"], "verify_exp": True},
    )


def _verify(token: str) -> Principal:
    import jwt
    try:
        claims = _decode(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token has expired")
    except jwt.InvalidTokenError as exc:
        # The reason is not echoed back: it tells an attacker which part of a
        # forged token to fix next.
        log.info("[auth] rejected token: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token has no subject")
    return Principal(user_id=sub, email=claims.get("email"))


async def current_principal(
    authorization: str | None = Header(default=None),
) -> Principal:
    """The caller, or a 401.

    Never returns an unauthenticated placeholder. A route that forgets to depend
    on this fails closed at the database instead, because an unset tenant
    matches no rows — but that is the second line, not the first.
    """
    if authorization and authorization.lower().startswith("bearer "):
        return _verify(authorization.split(" ", 1)[1].strip())

    if settings().allow_guest:
        return Principal(user_id="guest-local", email="guest@local",
                         is_guest=True)

    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "sign in to continue",
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentUser = Depends(current_principal)
