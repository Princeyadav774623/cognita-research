from limits import RateLimitItemPerMinute, storage, strategies
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import get_settings

# A blunt, IP-only cap applied to every request at the ASGI layer, before
# routing or dependency resolution. This exists specifically to bound
# unauthenticated abuse (garbage-token spam, scraping /health, etc.) that
# would otherwise never reach the per-user @limiter.limit() decorators on
# individual endpoints, since those only run once auth has already
# succeeded and FastAPI has called into the endpoint body.
_uri = get_settings().rate_limit_storage_uri
_storage = storage.storage_from_string(_uri) if _uri else storage.MemoryStorage()
_strategy = strategies.MovingWindowRateLimiter(_storage)
_GLOBAL_IP_LIMIT = RateLimitItemPerMinute(60)


def client_ip(request: Request) -> str:
    """The caller's address, not the load balancer's.

    request.client.host is the last hop. Behind any proxy that is the proxy
    itself, identical for every visitor, so a per-IP limit became a single
    global bucket throttling all users together. TRUSTED_PROXY_COUNT says how
    many hops we control; the entry before them is the real client. Left at 0
    (direct connections) the header is ignored entirely, because a spoofable
    header must not be trusted when nothing is in front of us.
    """
    hops = get_settings().trusted_proxy_count
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        chain = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(chain) >= hops:
            return chain[-hops]
    return request.client.host if request.client else "unknown"


class GlobalIPRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = client_ip(request)
        if not _strategy.hit(_GLOBAL_IP_LIMIT, ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests — please slow down."},
            )
        return await call_next(request)
