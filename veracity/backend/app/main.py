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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_analysis, routes_ask, routes_media
from app.config import settings

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-16s %(message)s",
    )
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

app.include_router(routes_media.router)
app.include_router(routes_analysis.router)
app.include_router(routes_ask.router)


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
        "remote_fetch": settings().allow_remote_fetch,
        "guest_mode": settings().allow_guest,
    }
