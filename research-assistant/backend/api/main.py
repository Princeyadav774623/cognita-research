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
from graph.research_graph import run_research, stream_research
from db import init_db, save_session, get_session, list_sessions, delete_session, delete_user_data
from billing import consume_quota, refund_quota, init_billing_db, QuotaExceededError
from rag.store import init_rag_db, delete_all_user_rag_data
from rag.embeddings import embed_query
from api.rag_routes import router as rag_router
from api.billing_routes import router as billing_router

configure_logging(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()

WS_QUERY_TIMEOUT_SECONDS = 15

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_billing_db()
    init_rag_db()
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
    yield


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


class ResearchResponse(BaseModel):
    session_id: str
    query: str
    final_report: str
    sources: list
    confidence: float
    verified_claims: list


# =============================================
# REST Endpoints
# =============================================

@app.get("/")
def root():
    return {"message": "Research Assistant API is running", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/api/research", response_model=ResearchResponse)
@limiter.limit("5/minute")
async def research(request: Request, body: ResearchRequest, user_id: str = Depends(get_current_user_id)):
    """
    Run full research pipeline.
    Returns complete report when all agents finish.
    """
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    if len(query) > 500:
        raise HTTPException(status_code=400, detail="Query too long (max 500 chars)")

    # Reserve one query against the user's monthly plan allowance before doing
    # any expensive work. slowapi's 5/minute limit above is burst protection,
    # not plan enforcement — the two are independent.
    try:
        consume_quota(user_id)
    except QuotaExceededError as e:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly quota exceeded ({e.status['queries_used']}/{e.status['quota_limit']}). "
                   "Upgrade to Pro for more queries.",
        )

    session_id = str(uuid.uuid4())
    logger.info(
        "New research request",
        extra={"session_id": session_id, "user_id": user_id, "query": query},
    )

    try:
        final_state = await run_research(query, session_id, user_id=user_id)
        save_session(session_id, user_id, query, final_state)

        logger.info(
            "Research request completed",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "confidence": final_state.get("overall_confidence", 0.0),
                "source_count": len(final_state.get("source_documents", [])),
            },
        )

        return ResearchResponse(
            session_id=session_id,
            query=query,
            final_report=final_state.get("final_report", ""),
            sources=[
                {"title": d["title"], "url": d["url"]}
                for d in final_state.get("source_documents", [])
            ],
            confidence=final_state.get("overall_confidence", 0.0),
            verified_claims=final_state.get("verified_claims", []),
        )

    except Exception as e:
        # Don't bill the user for our own failure.
        refund_quota(user_id)
        logger.error(
            "Research request failed",
            extra={"session_id": session_id, "user_id": user_id, "error": str(e)},
        )
        raise HTTPException(status_code=500, detail="Research pipeline failed")


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
    Client sends: {"query": "your question"}
    Server streams: step-by-step agent updates + final report
    """
    await websocket.accept()
    logger.info("[WebSocket] Client connected")

    # Tracked so a mid-pipeline failure can hand the reserved query back.
    user_id: str | None = None
    quota_consumed = False

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

        query = data.get("query", "").strip()

        if not query:
            await websocket.send_json({"type": "error", "message": "Query is required"})
            await websocket.close()
            return

        if len(query) > 500:
            await websocket.send_json({"type": "error", "message": "Query too long (max 500 chars)"})
            await websocket.close()
            return

        # Same plan enforcement as POST /api/research — without this the
        # WebSocket is a free, unmetered path to the exact same pipeline.
        try:
            consume_quota(user_id)
            quota_consumed = True
        except QuotaExceededError as e:
            await websocket.send_json({
                "type": "error",
                "message": f"Monthly quota exceeded ({e.status['queries_used']}/{e.status['quota_limit']}). "
                           "Upgrade to Pro for more queries.",
            })
            await websocket.close(code=4402)
            return

        session_id = str(uuid.uuid4())

        # Send start confirmation
        await websocket.send_json({
            "type": "start",
            "session_id": session_id,
            "message": f"Starting research for: {query}",
        })

        # Stream each agent's progress, accumulating the full state so we
        # can persist the completed session once streaming finishes.
        accumulated_state: dict = {}
        async for event in stream_research(query, session_id, user_id=user_id):
            # Token events carry generated text, not a state update — forward
            # them straight through so the client can render as it arrives.
            if event.get("type") == "token":
                await websocket.send_json({
                    "type": "token",
                    "node": event["node"],
                    "text": event["text"],
                })
                continue

            accumulated_state.update(event.get("state", {}))
            await websocket.send_json({
                "type": "progress",
                "node": event["node"],
                "step": event["step"],
                "data": event["data"],
            })

        save_session(session_id, user_id, query, accumulated_state)

        # Send completion signal, then close from the server side so the
        # client isn't racing us to close the same connection.
        await websocket.send_json({
            "type": "complete",
            "session_id": session_id,
        })
        await websocket.close(code=1000)

    except WebSocketDisconnect:
        logger.info("[WebSocket] Client disconnected")
    except Exception as e:
        # Don't bill the user for our own failure.
        if quota_consumed and user_id:
            refund_quota(user_id)
        logger.error(f"[WebSocket] Error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": "Research failed"})
            await websocket.close(code=1011)
        except Exception:
            pass


# =============================================
# Run server
# =============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
