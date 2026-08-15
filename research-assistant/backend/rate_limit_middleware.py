from limits import RateLimitItemPerMinute, storage, strategies
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# A blunt, IP-only cap applied to every request at the ASGI layer, before
# routing or dependency resolution. This exists specifically to bound
# unauthenticated abuse (garbage-token spam, scraping /health, etc.) that
# would otherwise never reach the per-user @limiter.limit() decorators on
# individual endpoints, since those only run once auth has already
# succeeded and FastAPI has called into the endpoint body.
_storage = storage.MemoryStorage()
_strategy = strategies.MovingWindowRateLimiter(_storage)
_GLOBAL_IP_LIMIT = RateLimitItemPerMinute(60)


class GlobalIPRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        if not _strategy.hit(_GLOBAL_IP_LIMIT, client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests — please slow down."},
            )
        return await call_next(request)
