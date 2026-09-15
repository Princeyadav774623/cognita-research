import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, text
from sqlalchemy.orm import relationship

from db import Base, engine, tenant_session

EMBEDDING_DIM = 384


class RagDocument(Base):
    __tablename__ = "rag_documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    status = Column(String, default="processing")  # processing | ready | error
    char_count = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    chunks = relationship("RagChunk", back_populates="document", cascade="all, delete-orphan")


class RagChunk(Base):
    __tablename__ = "rag_chunks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)

    document = relationship("RagDocument", back_populates="chunks")


class RagConversation(Base):
    __tablename__ = "rag_conversations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    messages = relationship("RagMessage", back_populates="conversation", cascade="all, delete-orphan")


class RagMessage(Base):
    __tablename__ = "rag_messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, ForeignKey("rag_conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    sources = Column(Text, nullable=True)  # JSON-encoded list of {filename, chunk_index}
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    conversation = relationship("RagConversation", back_populates="messages")


def init_rag_db():
    """Retained as a no-op call site. The rag_* tables, the pgvector extension
    and the HNSW index are all owned by Alembic now (see db.init_db)."""
    return None


def delete_all_user_rag_data(user_id: str) -> dict:
    """Cascade delete all RAG documents, embeddings, conversations, and messages for a user."""
    with tenant_session(user_id) as db:
        docs_deleted = db.query(RagDocument).filter(RagDocument.user_id == user_id).delete(synchronize_session=False)
        convs_deleted = db.query(RagConversation).filter(RagConversation.user_id == user_id).delete(synchronize_session=False)
        db.commit()
        return {"documents_deleted": docs_deleted, "conversations_deleted": convs_deleted}


# Re-exported so rag/retrieval.py and rag/chat_agent.py don't need to know
# about db.py's internals — they just need a session scoped to their user.
get_tenant_session = tenant_session

