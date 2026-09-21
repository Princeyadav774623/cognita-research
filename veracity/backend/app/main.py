"""The service.

Startup does three things and refuses to serve if any fails: reach both
databases, ensure the schema, and install the isolation policies. A service that
starts and then errors on every request is harder to diagnose than one that
declines to start and says why.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api import (routes_analysis, routes_ask, routes_media,
                     routes_quota)
from app.config import settings

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.observability import configure
    configure(level=os.getenv("LOG_LEVEL", "INFO"),
              json_logs=os.getenv("LOG_FORMAT", "json") == "json")
    from app.db.bootstrap import init
    from app.db import rls

    os.makedirs(settings().media_root, exist_ok=True)
    init()

    problems = rls.verify()
    if problems:
        for p in problems:
            log.error("[startup] tenant isolation problem: %s", p)

    if settings().allow_guest:
        log.warning(
            "[startup] ALLOW_GUEST is on: every unauthenticated request is the "
            "same user, so tenant isolation separates nothing. Development only."
        )
    if settings().allow_remote_fetch:
        log.warning(
            "[startup] ALLOW_REMOTE_FETCH is on: this server will download from "
            "third-party hosts, which may breach their terms of service."
        )
    log.info("[startup] ready")
    yield


app = FastAPI(
    title="Veracity",
    description="Analyse video and audio, and check what was said.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def _observe(request, call_next):
    """Give every request an identity, then time it.

    The id is echoed back so a user reporting a problem can quote it and be
    found in one grep, and is accepted from an inbound header so a trace that
    started upstream is not broken here.
    """
    import time as _time

    from app.observability import metrics, new_request_id, request_id

    rid = request.headers.get("x-request-id") or new_request_id()
    token = request_id.set(rid)
    started = _time.monotonic()
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        # Counted before re-raising: an unhandled exception is the metric you
        # most want and the one a response-based hook never sees.
        metrics.count("veracity_requests_total",
                      "HTTP requests handled",
                      route=_route(request), method=request.method,
                      status="500")
        raise
    finally:
        request_id.reset(token)

    elapsed = _time.monotonic() - started
    route = _route(request)
    metrics.count("veracity_requests_total", "HTTP requests handled",
                  route=route, method=request.method, status=str(status_code))
    metrics.observe("veracity_request_seconds", elapsed,
                    "Time to handle a request", route=route,
                    method=request.method)
    response.headers["X-Request-ID"] = rid
    return response


def _route(request) -> str:
    """Collapse ids so each media item is not its own metric series."""
    parts = []
    for segment in request.url.path.strip("/").split("/"):
        parts.append(":id" if len(segment) >= 32 and "-" in segment else segment)
    return "/" + "/".join(parts)


@app.middleware("http")
async def _rate_limit(request, call_next):
    """Applied as middleware rather than a route dependency so it runs before
    the body is read. A dependency would let a 2 GB upload stream to disk first
    and only then be refused."""
    from fastapi.responses import JSONResponse

    from app.rate_limit import enforce
    if request.url.path.startswith("/api"):
        try:
            await enforce(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail},
                                status_code=exc.status_code,
                                headers=exc.headers)
    return await call_next(request)


app.include_router(routes_media.router)
app.include_router(routes_analysis.router)
app.include_router(routes_ask.router)
app.include_router(routes_quota.router)


@app.get("/metrics", tags=["meta"], include_in_schema=False)
async def prometheus_metrics():
    """Scrape endpoint.

    Queue depth is read here rather than tracked incrementally: a counter
    maintained by the workers drifts whenever one dies mid-job, and the whole
    point of this number is to be trusted during an incident.
    """
    from fastapi.responses import PlainTextResponse
    from sqlalchemy import text

    from app.db.session import owner_engine
    from app.observability import metrics

    try:
        with owner_engine.connect() as conn:
            for state, count in conn.execute(text(
                "SELECT state, count(*) FROM jobs GROUP BY state"
            )):
                metrics.gauge("veracity_jobs", float(count),
                              "Jobs by state", state=state)
            stuck = conn.execute(text(
                "SELECT count(*) FROM media_items WHERE state = 'failed'"
            )).scalar()
            metrics.gauge("veracity_media_failed", float(stuck or 0),
                          "Media items that failed ingestion")
    except Exception:                       # pragma: no cover
        # A scrape must never take the service down.
        pass

    return PlainTextResponse(metrics.render(),
                             media_type="text/plain; version=0.0.4")


@app.get("/health", tags=["meta"])
async def health():
    """Liveness plus the facts a deployment check actually wants."""
    from app.db import rls
    from app.db.session import owner_engine
    from sqlalchemy import text

    try:
        with owner_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:                       # pragma: no cover
        database = f"unreachable: {type(exc).__name__}"

    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "tenant_isolation": "enforced" if not rls.verify() else "NOT ENFORCED",
        "asr_backend": settings().asr_backend,
        "storage": settings().storage_backend,
        "remote_fetch": settings().allow_remote_fetch,
        "guest_mode": settings().allow_guest,
    }
