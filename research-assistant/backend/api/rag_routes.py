import logging
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from rate_limit import limiter
from auth import get_current_user_id
from rag.retrieval import ingest_document, list_documents, delete_document
from rag.chat_agent import (
    chat,
    get_conversation_history,
    list_conversations,
    delete_conversation,
)
from rag.ingest import ALLOWED_EXTENSIONS, MAX_FILE_SIZE_BYTES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag"])


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    top_k: Optional[int] = Field(default=4, ge=1, le=10)
    temperature: Optional[float] = Field(default=0.2, ge=0.0, le=1.0)
    similarity_threshold: Optional[float] = Field(default=0.55, ge=0.0, le=1.0)


@router.post("/upload")
@limiter.limit("10/minute")
async def upload_document(
    request: Request, file: UploadFile = File(...), user_id: str = Depends(get_current_user_id)
):
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    # Read in bounded chunks and bail as soon as the limit is passed, rather
    # than buffering the whole upload first and measuring afterwards — an
    # oversized body would otherwise be spooled to disk in full before being
    # rejected, which is free resource exhaustion for an authenticated caller.
    content = bytearray()
    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail="File too large (max 15MB)")

    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    document = await run_in_threadpool(ingest_document, user_id, file.filename, bytes(content))
    if document["status"] == "error":
        raise HTTPException(status_code=422, detail=document["error"])
    return document


@router.get("/documents")
@limiter.limit("30/minute")
def get_documents(request: Request, user_id: str = Depends(get_current_user_id)):
    return {"documents": list_documents(user_id)}


@router.delete("/documents/{document_id}")
@limiter.limit("30/minute")
def remove_document(request: Request, document_id: str, user_id: str = Depends(get_current_user_id)):
    deleted = delete_document(document_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": document_id}


@router.post("/chat")
@limiter.limit("20/minute")
def chat_endpoint(request: Request, body: ChatRequest, user_id: str = Depends(get_current_user_id)):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(message) > 1000:
        raise HTTPException(status_code=400, detail="Message too long (max 1000 chars)")

    return chat(
        user_id=user_id,
        conversation_id=body.conversation_id,
        message=message,
        top_k=body.top_k or 4,
        temperature=body.temperature if body.temperature is not None else 0.2,
        similarity_threshold=body.similarity_threshold if body.similarity_threshold is not None else 0.55,
    )


@router.get("/conversations")
@limiter.limit("30/minute")
def get_conversations_list(request: Request, user_id: str = Depends(get_current_user_id)):
    """List all RAG conversation sessions for the active user."""
    return {"conversations": list_conversations(user_id)}


@router.get("/conversations/{conversation_id}")
@limiter.limit("30/minute")
def get_conversation(
    request: Request, conversation_id: str, user_id: str = Depends(get_current_user_id)
):
    history = get_conversation_history(conversation_id, user_id)
    if not history:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation_id": conversation_id, "messages": history}


@router.delete("/conversations/{conversation_id}")
@limiter.limit("30/minute")
def delete_conversation_endpoint(
    request: Request, conversation_id: str, user_id: str = Depends(get_current_user_id)
):
    deleted = delete_conversation(conversation_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": conversation_id}
