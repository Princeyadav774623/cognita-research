import json
import logging

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from config import get_settings
from utils import invoke_with_retry
from rag.store import RagConversation, RagMessage, get_tenant_session
from rag.retrieval import retrieve_relevant_chunks

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_HISTORY_MESSAGES = 10  # last N messages included as conversation context

SYSTEM_PROMPT = """You are a helpful assistant that answers questions using ONLY the
provided document excerpts. Rules:
- Base your answer strictly on the excerpts given below.
- If the excerpts don't contain the answer, say so plainly instead of guessing.
- Cite the source filename inline when referencing a specific fact, like (source: report.pdf).
- Be concise and direct.
"""


def chat(user_id: str, conversation_id: str | None, message: str) -> dict:
    try:
        with get_tenant_session(user_id) as db:
            conversation = _get_or_create_conversation(db, user_id, conversation_id)

            history = (
                db.query(RagMessage)
                .filter(RagMessage.conversation_id == conversation.id)
                .order_by(RagMessage.created_at.asc())
                .all()
            )

            chunks = retrieve_relevant_chunks(user_id, message)
            context = _format_context(chunks)

            llm = ChatGroq(
                model=settings.groq_model_smart,
                api_key=settings.groq_api_key,
                temperature=0.2,
                max_tokens=1024,
            )

            messages = [SystemMessage(content=SYSTEM_PROMPT)]
            for msg in history[-MAX_HISTORY_MESSAGES:]:
                messages.append(
                    AIMessage(content=msg.content) if msg.role == "assistant" else HumanMessage(content=msg.content)
                )
            messages.append(HumanMessage(content=f"Document excerpts:\n{context}\n\nQuestion: {message}"))

            if not chunks:
                answer = "I don't have any documents to search yet — upload one first, then ask me about it."
            else:
                response = invoke_with_retry(llm, messages)
                answer = response.content.strip()

            sources = [{"filename": c["filename"], "chunk_index": c["chunk_index"]} for c in chunks]

            db.add(RagMessage(conversation_id=conversation.id, role="user", content=message))
            db.add(RagMessage(
                conversation_id=conversation.id, role="assistant", content=answer,
                sources=json.dumps(sources),
            ))
            db.commit()

            return {
                "conversation_id": conversation.id,
                "answer": answer,
                "sources": sources,
            }
    except Exception as e:
        logger.error(f"[RAGChat] Error: {e}")
        return {
            "conversation_id": conversation_id or "",
            "answer": "Sorry, something went wrong answering that question.",
            "sources": [],
        }


def get_conversation_history(conversation_id: str, user_id: str) -> list[dict]:
    with get_tenant_session(user_id) as db:
        conversation = (
            db.query(RagConversation)
            .filter(RagConversation.id == conversation_id, RagConversation.user_id == user_id)
            .first()
        )
        if not conversation:
            return []

        messages = (
            db.query(RagMessage)
            .filter(RagMessage.conversation_id == conversation_id)
            .order_by(RagMessage.created_at.asc())
            .all()
        )
        return [
            {
                "role": m.role,
                "content": m.content,
                "sources": json.loads(m.sources) if m.sources else [],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]


def _get_or_create_conversation(db, user_id: str, conversation_id: str | None) -> RagConversation:
    if conversation_id:
        existing = (
            db.query(RagConversation)
            .filter(RagConversation.id == conversation_id, RagConversation.user_id == user_id)
            .first()
        )
        if existing:
            return existing
        # Either it doesn't exist or belongs to another user — either way,
        # silently starting a fresh conversation is safer than erroring in
        # a way that reveals whether the id exists for someone else.
    conversation = RagConversation(user_id=user_id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "No documents available."
    parts = []
    for c in chunks:
        parts.append(f"[{c['filename']} — chunk {c['chunk_index']}]\n{c['content']}")
    return "\n\n".join(parts)
