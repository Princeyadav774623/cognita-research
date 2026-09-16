import logging
from datetime import datetime, timedelta, timezone

from rag.store import RagDocument, RagChunk, get_tenant_session
from rag.ingest import extract_text, chunk_text, IngestError
from rag.embeddings import embed_texts, embed_query

logger = logging.getLogger(__name__)

TOP_K = 6


def create_document_record(user_id: str, filename: str) -> dict:
    """Register the upload and return immediately, before any parsing.

    Extraction, chunking and embedding used to happen inside the request, so a
    long PDF held the connection open and could outlive a proxy timeout. The
    status field already modelled processing -> ready; nothing was ever driving
    it. Now it is real.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
    with get_tenant_session(user_id) as db:
        document = RagDocument(user_id=user_id, filename=filename, file_type=ext, status="processing")
        db.add(document)
        db.commit()
        db.refresh(document)
        return _document_to_dict(document)


def process_document(user_id: str, document_id: str, filename: str, content: bytes) -> None:
    """Do the slow half: extract, chunk, embed, store. Runs after the response.

    Any failure is recorded on the row rather than raised, because there is no
    longer a caller waiting to receive it — the document's status is how the
    user finds out.
    """
    with get_tenant_session(user_id) as db:
        document = (
            db.query(RagDocument)
            .filter(RagDocument.id == document_id, RagDocument.user_id == user_id)
            .first()
        )
        if not document:
            logger.warning(f"[RAG] Document {document_id} vanished before processing")
            return

        try:
            text = extract_text(filename, content)
            chunks = chunk_text(text)
            if not chunks:
                raise IngestError("No content could be extracted from this file")

            vectors = embed_texts(chunks)
            for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
                db.add(RagChunk(document_id=document.id, chunk_index=i, content=chunk, embedding=vector))

            document.status = "ready"
            document.char_count = len(text)
            document.chunk_count = len(chunks)
            db.commit()
            logger.info(f"[RAG] Ingested '{filename}' for user {user_id}: {len(chunks)} chunks")

        except IngestError as e:
            document.status = "error"
            document.error = str(e)
            db.commit()
            logger.warning(f"[RAG] Failed to ingest '{filename}': {e}")
        except Exception as e:
            document.status = "error"
            document.error = "Unexpected error while processing file"
            db.commit()
            logger.error(f"[RAG] Unexpected error ingesting '{filename}': {e}")


def ingest_document(user_id: str, filename: str, content: bytes) -> dict:
    """Synchronous ingest, kept for scripts and tests that want the finished
    record back in one call."""
    record = create_document_record(user_id, filename)
    process_document(user_id, record["id"], filename, content)
    with get_tenant_session(user_id) as db:
        doc = db.query(RagDocument).filter(RagDocument.id == record["id"]).first()
        return _document_to_dict(doc) if doc else record


# A document left mid-ingest for longer than this was almost certainly
# orphaned by a restart: extraction and embedding take seconds, not minutes.
STALE_PROCESSING_MINUTES = 15


def reap_stale_processing(user_id: str) -> int:
    """Mark documents abandoned by a restart as failed, instead of leaving them
    spinning forever.

    Ingestion runs in the web process, so a deploy or crash between "row
    created" and "embedding finished" leaves a row at processing with nothing
    left to advance it. The UI polls while anything is processing, so that row
    span a spinner indefinitely and the user had no way to tell it apart from
    a slow upload — or to retry it.

    A durable queue is the real fix; this makes the failure visible and
    recoverable in the meantime.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_PROCESSING_MINUTES)
    with get_tenant_session(user_id) as db:
        stale = (
            db.query(RagDocument)
            .filter(
                RagDocument.user_id == user_id,
                RagDocument.status == "processing",
                RagDocument.created_at < cutoff,
            )
            .all()
        )
        for doc in stale:
            doc.status = "error"
            doc.error = "Indexing was interrupted before it finished. Upload the file again."
        if stale:
            db.commit()
            logger.warning(
                f"[RAG] Reaped {len(stale)} document(s) stuck in processing for user {user_id}"
            )
        return len(stale)


def list_documents(user_id: str) -> list[dict]:
    # Checked here because this is what the client polls: a stuck row is
    # noticed the next time anyone looks at the list, with no scheduler needed.
    reap_stale_processing(user_id)

    with get_tenant_session(user_id) as db:
        docs = (
            db.query(RagDocument)
            .filter(RagDocument.user_id == user_id)
            .order_by(RagDocument.created_at.desc())
            .all()
        )
        return [_document_to_dict(d) for d in docs]


def delete_document(document_id: str, user_id: str) -> bool:
    with get_tenant_session(user_id) as db:
        doc = (
            db.query(RagDocument)
            .filter(RagDocument.id == document_id, RagDocument.user_id == user_id)
            .first()
        )
        if not doc:
            return False
        db.delete(doc)
        db.commit()
        return True


def retrieve_relevant_chunks(user_id: str, query: str, top_k: int = TOP_K, limit: int | None = None) -> list[dict]:
    """Embed the query and find the most semantically similar chunks across
    this user's ready documents only, via pgvector cosine distance."""
    effective_k = limit if limit is not None else top_k
    with get_tenant_session(user_id) as db:
        query_vector = embed_query(query)
        # pgvector's cosine_distance is 1 - cosine_similarity, so similarity
        # is recovered directly from it rather than estimated.
        distance = RagChunk.embedding.cosine_distance(query_vector)
        rows = (
            db.query(RagChunk, RagDocument.filename, distance.label("distance"))
            .join(RagDocument, RagChunk.document_id == RagDocument.id)
            .filter(RagDocument.status == "ready", RagDocument.user_id == user_id)
            .order_by(distance)
            .limit(effective_k)
            .all()
        )
        return [
            {
                "content": chunk.content,
                "filename": filename,
                "chunk_index": chunk.chunk_index,
                "similarity": max(0.0, min(1.0, 1.0 - float(dist))),
            }
            for chunk, filename, dist in rows
        ]


def _document_to_dict(doc: RagDocument) -> dict:
    return {
        "id": doc.id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "status": doc.status,
        "char_count": doc.char_count,
        "chunk_count": doc.chunk_count,
        "error": doc.error,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }
