import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import jwt

from config import get_settings
from logging_config import configure_logging
from rate_limit import limiter
from rate_limit_middleware import GlobalIPRateLimitMiddleware
from auth import get_current_user_id, verify_token
import jobs
from db import init_db, get_session, list_sessions, delete_session, delete_user_data
from rls import apply_rls_policies
from billing import consume_quota, refund_quota, init_billing_db, QuotaExceededError
from rag.store import init_rag_db, delete_all_user_rag_data
from rag.embeddings import embed_query
from api.rag_routes import router as rag_router
from api.billing_routes import router as billing_router

configure_logging(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()

WS_QUERY_TIMEOUT_SECONDS = 15
# How often an open WebSocket checks for new events. The worker flushes every
# quarter-second, so polling much faster than this buys nothing.
WS_POLL_SECONDS = 0.3
# Proxies and load balancers drop a connection that is silent for ~60s, and a
# single slow model call can be quieter than that.
WS_KEEPALIVE_SECONDS = 20

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_billing_db()
    init_rag_db()
    # Last, because a policy can only be attached to a table that exists —
    # research_sessions, user_subscriptions and the rag_* tables are each
    # created by one of the three calls above.
    apply_rls_policies()
    # fastembed loads its ONNX weights lazily on first use — measured 2.2s
    # cold vs 2ms warm. Left alone, whichever user happens to send the first
    # RAG chat message after a deploy pays that latency. Warming it here means
    # it's paid once, at startup, by nobody in particular. A failure here
    # (e.g. the model can't be fetched) is logged but doesn't block the rest
    # of the app — Deep Research and auth don't depend on it.
    try:
        embed_query("warmup")
        logger.info("[Startup] Embedding model warmed")
    except Exception as e:
        logger.error(f"[Startup] Failed to warm embedding model: {e}")

    worker_stop = asyncio.Event()
    worker_tasks: list[asyncio.Task] = []
    if settings.embedded_worker:
        import worker
        worker_tasks = [asyncio.create_task(worker.worker_loop(worker_stop))
                        for _ in range(max(1, settings.worker_concurrency))]
        worker_tasks.append(asyncio.create_task(worker.housekeeping(worker_stop)))
        logger.info(f"[Startup] Embedded research worker started ({jobs.WORKER_ID})")
    yield
    # Shutdown hands any running job back to the queue (see worker.run_job),
    # so the next instance restarts it instead of waiting out the lease.
    worker_stop.set()
    for task in worker_tasks:
        task.cancel()
    await asyncio.gather(*worker_tasks, return_exceptions=True)


app = FastAPI(
    title="Multi-Agent Research Assistant API",
    description="AI-powered research with 5 specialized agents",
    version="1.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# Runs at the ASGI layer, before FastAPI resolves dependencies — without
# this, a request with a missing/invalid token fails auth (401) before ever
# reaching the @limiter.limit()-decorated endpoint body, so garbage-token
# spam would never actually get rate-limited.
app.add_middleware(GlobalIPRateLimitMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all so callers always get JSON, never a raw stack trace."""
    logger.error(f"[API] Unhandled error on {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(rag_router)
app.include_router(billing_router)

# Allow frontend to connect — configurable so a real deployment isn't stuck
# with a hardcoded placeholder domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================
# Request / Response Models
# =============================================

class ResearchRequest(BaseModel):
    query: str


class ResearchQueued(BaseModel):
    session_id: str
    query: str
    state: str


def _validate_query(query: str) -> str | None:
    """The error message for an unacceptable query, or None."""
    if not query:
        return "Query cannot be empty"
    if len(query) > 500:
        return "Query too long (max 500 chars)"
    return None


def _quota_message(e: QuotaExceededError) -> str:
    return (f"Monthly quota exceeded ({e.status['queries_used']}/{e.status['quota_limit']}). "
            "Upgrade to Pro for more queries.")


def _submit(user_id: str, session_id: str, query: str) -> dict:
    """Reserve one query of allowance and queue the research.

    Reserved up front so concurrent submissions cannot all pass the check
    before any of them is counted; handed back if the job never lands.
    """
    consume_quota(user_id)
    try:
        return jobs.enqueue(user_id, session_id, query)
    except Exception:
        refund_quota(user_id)
        raise


def _parse_session_id(value) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        return None


# =============================================
# REST Endpoints
# =============================================

@app.get("/")
def root():
    return {"message": "Research Assistant API is running", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/api/research", response_model=ResearchQueued, status_code=202)
@limiter.limit("5/minute")
def research(request: Request, body: ResearchRequest, user_id: str = Depends(get_current_user_id)):
    """Queue a research run and return at once.

    Follow it with GET /api/research/{id}/status, or attach to
    /ws/research with the returned session_id for live progress. The report
    is at GET /api/research/{id} once the state is "done".
    """
    query = body.query.strip()
    problem = _validate_query(query)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    # slowapi's 5/minute limit above is burst protection, not plan
    # enforcement — the quota reserved in _submit is the plan.
    session_id = str(uuid.uuid4())
    try:
        job = _submit(user_id, session_id, query)
    except QuotaExceededError as e:
        raise HTTPException(status_code=402, detail=_quota_message(e))

    logger.info("Research queued", extra={"session_id": session_id, "user_id": user_id})
    return ResearchQueued(session_id=session_id, query=query, state=job["state"])


@app.get("/api/research/{session_id}/status")
@limiter.limit("60/minute")
def research_status(request: Request, session_id: str, user_id: str = Depends(get_current_user_id)):
    job = jobs.get_job(user_id, session_id)
    if not job:
        raise HTTPException(status_code=404, detail="Research not found")
    return job


@app.post("/api/research/{session_id}/cancel")
@limiter.limit("30/minute")
def cancel_research(request: Request, session_id: str, user_id: str = Depends(get_current_user_id)):
    """Stop a queued or running research and return its query to the allowance.

    Closing the WebSocket no longer stops anything — the run carries on so a
    refresh or a dropped connection can pick it back up — so stopping has to
    be asked for.
    """
    if not jobs.cancel(user_id, session_id):
        if jobs.get_job(user_id, session_id) is None:
            raise HTTPException(status_code=404, detail="Research not found")
        raise HTTPException(status_code=409, detail="Research has already finished")
    refund_quota(user_id)
    logger.info("Research cancelled", extra={"session_id": session_id, "user_id": user_id})
    return {"cancelled": session_id}


@app.get("/api/history")
@limiter.limit("30/minute")
def history(request: Request, limit: int = 50, user_id: str = Depends(get_current_user_id)):
    """Return past research sessions, most recent first."""
    return {"sessions": list_sessions(user_id=user_id, limit=min(limit, 100))}


@app.get("/api/research/{session_id}")
@limiter.limit("30/minute")
def get_research(request: Request, session_id: str, user_id: str = Depends(get_current_user_id)):
    """Fetch a single past research session by id."""
    record = get_session(session_id, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Session not found")
    return record


@app.delete("/api/research/{session_id}")
@limiter.limit("30/minute")
def delete_research(request: Request, session_id: str, user_id: str = Depends(get_current_user_id)):
    """Delete a past research session."""
    deleted = delete_session(session_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": session_id}


@app.delete("/api/user/me")
@limiter.limit("5/minute")
def delete_current_user_account(request: Request, user_id: str = Depends(get_current_user_id)):
    """Delete all user data (research sessions, RAG documents, and conversation history) under GDPR."""
    sessions_deleted = delete_user_data(user_id)
    # Queued and recent jobs hold the query text, so they go too.
    jobs.delete_user_jobs(user_id)
    rag_deleted = delete_all_user_rag_data(user_id)
    logger.info(f"[Auth] Purged all account data for user {user_id}")
    return {
        "status": "purged",
        "user_id": user_id,
        "research_sessions_deleted": sessions_deleted,
        "rag_data_deleted": rag_deleted,
    }


# =============================================
# WebSocket — Live Streaming
# =============================================

@app.websocket("/ws/research")
async def research_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time agent progress.

    Client sends: {"token", "session_id", "query", "after"}
      - session_id is generated by the client, so a retry after a dropped
        handshake attaches to the run it already started instead of starting
        (and billing) a second one.
      - If no research with that id exists yet, it is queued from "query".
      - "after" is the last event id the client saw; 0 replays from the start.
    Server streams: the run's events, each carrying "seq", ending with
    "complete" or "error". Disconnecting does not stop the research.
    """
    await websocket.accept()
    logger.info("[WebSocket] Client connected")

    try:
        # Receive the query from client, bounded so a silent connection
        # doesn't hold a socket open indefinitely.
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=WS_QUERY_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await websocket.send_json({"type": "error", "message": "Timed out waiting for query"})
            await websocket.close()
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_json({"type": "error", "message": "Invalid JSON payload"})
            await websocket.close()
            return

        # Browsers can't set custom headers on a WebSocket handshake, so the
        # client sends its Supabase JWT as part of the first message instead.
        token = data.get("token", "")
        try:
            claims = verify_token(token)
            user_id = claims["sub"]
        except jwt.PyJWTError:
            await websocket.send_json({"type": "error", "message": "Authentication required"})
            await websocket.close(code=4401)
            return

        session_id = _parse_session_id(data.get("session_id")) or str(uuid.uuid4())
        try:
            after = max(0, int(data.get("after") or 0))
        except (ValueError, TypeError):
            after = 0

        job = await asyncio.to_thread(jobs.get_job, user_id, session_id)
        if job is None:
            query = data.get("query", "").strip()
            problem = _validate_query(query)
            if problem:
                await websocket.send_json({"type": "error", "message": problem})
                await websocket.close()
                return
            # Same plan enforcement as POST /api/research — without this the
            # WebSocket is a free, unmetered path to the exact same pipeline.
            try:
                job = await asyncio.to_thread(_submit, user_id, session_id, query)
            except QuotaExceededError as e:
                await websocket.send_json({"type": "error", "message": _quota_message(e)})
                await websocket.close(code=4402)
                return

        await websocket.send_json({
            "type": "start",
            "session_id": session_id,
            "message": f"Starting research for: {job['query']}",
        })

        last_sent = asyncio.get_running_loop().time()
        while True:
            events = await asyncio.to_thread(jobs.events_after, user_id, session_id, after)
            for seq, payload in events:
                after = seq
                await websocket.send_json({**payload, "seq": seq})
                if payload.get("type") in ("complete", "error"):
                    # Close from the server side so the client isn't racing
                    # us to close the same connection.
                    await websocket.close(code=1000)
                    return
            if events:
                last_sent = asyncio.get_running_loop().time()
                continue

            # Done and failed runs end with their own event, so only a
            # cancellation (or a job deleted under us) can leave nothing to send.
            job = await asyncio.to_thread(jobs.get_job, user_id, session_id)
            if job is None or job["state"] == "cancelled":
                await websocket.send_json({"type": "error", "message": "Research stopped."})
                await websocket.close(code=1000)
                return

            if asyncio.get_running_loop().time() - last_sent >= WS_KEEPALIVE_SECONDS:
                await websocket.send_json({"type": "keepalive"})
                last_sent = asyncio.get_running_loop().time()
            await asyncio.sleep(WS_POLL_SECONDS)

    except WebSocketDisconnect:
        # The research carries on; the client can reattach with its id.
        logger.info("[WebSocket] Client disconnected")
    except Exception as e:
        # A fault in this connection, not in the research — which is still
        # running in the worker. No "error" frame, so the client reconnects
        # and resumes rather than telling the user the run failed.
        logger.error(f"[WebSocket] Error: {e}")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


# =============================================
# Run server
# =============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
