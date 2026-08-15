import logging

from fastapi import APIRouter, Request, UploadFile, File, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from rate_limit import limiter
from auth import get_current_user_id
from rag.retrieval import ingest_document, list_documents, delete_document
from rag.chat_agent import chat, get_conversation_history
from rag.ingest import ALLOWED_EXTENSIONS, MAX_FILE_SIZE_BYTES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag"])


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


@router.post("/upload")
@limiter.limit("10/minute")
async def upload_document(
    request: Request, file: UploadFile = File(...), user_id: str = Depends(get_current_user_id)
):
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 15MB)")

    document = await run_in_threadpool(ingest_document, user_id, file.filename, content)
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
@limiter.limit("15/minute")
def chat_endpoint(request: Request, body: ChatRequest, user_id: str = Depends(get_current_user_id)):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(message) > 1000:
        raise HTTPException(status_code=400, detail="Message too long (max 1000 chars)")

    return chat(user_id, body.conversation_id, message)


@router.get("/conversations/{conversation_id}")
@limiter.limit("30/minute")
def get_conversation(
    request: Request, conversation_id: str, user_id: str = Depends(get_current_user_id)
):
    history = get_conversation_history(conversation_id, user_id)
    if not history:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation_id": conversation_id, "messages": history}
