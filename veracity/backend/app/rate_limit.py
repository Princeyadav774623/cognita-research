"""Request-rate limiting, shared across instances.

Distinct from quotas, which meter *consumption* over a month. This meters
*requests* over seconds, and the two catch different problems: a quota stops an
expensive month, a rate limit stops one client saturating the service in a
minute — including before it has spent anything, which is when a scraper or a
runaway retry loop does its damage.

Counters live in Postgres rather than in process memory. In-memory works
perfectly on one instance and silently multiplies the effective limit by the
number of instances the moment you scale out, which is exactly when a limit
matters. Redis would be faster and is another thing to run, back up and reason
about; at this request volume a single indexed upsert is not the bottleneck.

Fixed windows rather than a sliding log: a client can send up to 2x the limit
across a window boundary, and that is an acceptable trade for one row per client
per window instead of one row per request.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.db.session import owner_session

log = logging.getLogger("rate_limit")


@dataclass(frozen=True)
class Limit:
    requests: int
    window_seconds: int

    @property
    def label(self) -> str:
        return f"{self.requests} per {self.window_seconds}s"


# Priced by what the request costs us, not by how it is spelled. Starting a
# transcription or an analysis is minutes of somebody's compute; listing media
# is an indexed read.
EXPENSIVE = Limit(requests=10, window_seconds=60)
MODERATE = Limit(requests=30, window_seconds=60)
CHEAP = Limit(requests=240, window_seconds=60)

_RULES: tuple[tuple[str, str, Limit], ...] = (
    ("POST", "/api/media", EXPENSIVE),
    ("POST", "/api/media/url", EXPENSIVE),
    ("POST", "/analysis", EXPENSIVE),
    ("POST", "/ask", MODERATE),
    ("DELETE", "/api/media", MODERATE),
)


def limit_for(method: str, path: str) -> Limit:
    for rule_method, fragment, limit in _RULES:
        if method == rule_method and fragment in path:
            return limit
    return CHEAP


def identity(request: Request) -> str:
    """Who to count against.

    The authenticated subject when there is one. Otherwise the peer address —
    and deliberately not a forwarded header, which a client sets itself and can
    rotate freely to get an unlimited number of buckets. A deployment behind a
    trusted proxy has to opt in by resolving the real address before this point.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        # The token is not verified here — that happens in the route's
        # dependency. Hashing the credential is enough to bucket by client
        # without this becoming a second, weaker auth path.
        import hashlib
        return "tok:" + hashlib.sha256(auth.encode()).hexdigest()[:32]
    return "ip:" + (request.client.host if request.client else "unknown")


def check(key: str, limit: Limit) -> tuple[bool, int, int]:
    """Count one request. Returns (allowed, used, seconds until the window ends)."""
    now = int(time.time())
    window_start = now - (now % limit.window_seconds)
    resets_in = window_start + limit.window_seconds - now

    with owner_session() as session:
        # One statement: insert the window or increment it. Two statements would
        # let concurrent requests each insert and lose one another's count.
        row = session.execute(text("""
            INSERT INTO rate_limits (bucket, window_start, hits)
            VALUES (:bucket, :window_start, 1)
            ON CONFLICT (bucket, window_start)
            DO UPDATE SET hits = rate_limits.hits + 1
            RETURNING hits
        """), {"bucket": key, "window_start": window_start}).first()
        used = int(row[0]) if row else 1

        # Opportunistic cleanup. A dedicated job would be tidier and is another
        # thing to deploy; one delete every few hundred requests keeps the table
        # bounded without one.
        if used == 1 and hash(key) % 200 == 0:
            session.execute(text(
                "DELETE FROM rate_limits WHERE window_start < :cutoff"
            ), {"cutoff": now - 3600})

    return used <= limit.requests, used, resets_in


async def enforce(request: Request) -> None:
    """Raise 429 when a caller is over its limit for this route."""
    limit = limit_for(request.method, request.url.path)
    key = f"{identity(request)}|{request.method}|{_bucket_path(request.url.path)}"
    try:
        # On the thread pool: this runs before every API request, and a
        # database round trip on the event loop would serialise all of them.
        allowed, used, resets_in = await run_in_threadpool(check, key, limit)
    except Exception as exc:
        # A limiter that takes the service down when its own storage hiccups is
        # worse than one that briefly lets traffic through. Fail open, loudly.
        log.error("[rate_limit] check failed, allowing request: %s", exc)
        return

    if not allowed:
        from app.observability import metrics
        metrics.count("veracity_rate_limited_total",
                      "Requests refused by the rate limiter",
                      route=_bucket_path(request.url.path),
                      method=request.method)
        log.info("[rate_limit] %s over %s (%d used)", key, limit.label, used)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"too many requests — the limit is {limit.label}. "
            f"Try again in {resets_in}s.",
            headers={"Retry-After": str(resets_in)},
        )


def _bucket_path(path: str) -> str:
    """Collapse ids so every media item does not get its own allowance."""
    parts = []
    for segment in path.strip("/").split("/"):
        parts.append(":id" if len(segment) >= 32 and "-" in segment else segment)
    return "/" + "/".join(parts)
