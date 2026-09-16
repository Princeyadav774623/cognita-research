import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

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


# How many candidates each retriever contributes before fusion. Wider than the
# final k on purpose: fusion can only promote something one side ranked, so a
# narrow candidate list throws away the recall hybrid search exists to gain.
CANDIDATE_POOL = 20

# Reciprocal Rank Fusion constant. Fuses by *rank*, not score, which is what
# makes it usable here: cosine similarity and ts_rank are different scales with
# no meaningful conversion between them, and normalising one onto the other
# invents a relationship that does not exist. 60 is the value from the original
# paper and is not sensitive.
RRF_K = 60


def _vector_candidates(db, user_id: str, query: str, limit: int) -> list[tuple[str, float]]:
    """(chunk_id, cosine similarity), best first."""
    query_vector = embed_query(query)
    # pgvector's cosine_distance is 1 - cosine_similarity, so similarity comes
    # back directly rather than being estimated.
    distance = RagChunk.embedding.cosine_distance(query_vector)
    rows = (
        db.query(RagChunk.id, distance.label("distance"))
        .join(RagDocument, RagChunk.document_id == RagDocument.id)
        .filter(RagDocument.status == "ready", RagDocument.user_id == user_id)
        .order_by(distance)
        .limit(limit)
        .all()
    )
    return [(cid, max(0.0, min(1.0, 1.0 - float(d)))) for cid, d in rows]


def _keyword_candidates(db, user_id: str, query: str, limit: int) -> list[str]:
    """Chunk ids ranked by Postgres full-text relevance, best first.

    websearch_to_tsquery rather than plainto_tsquery: it accepts what people
    actually type — quoted phrases, OR, leading minus — and, unlike
    to_tsquery, never raises on punctuation. A query that throws here would
    take the whole retrieval down with it.
    """
    if db.bind.dialect.name != "postgresql":
        return []   # SQLite in unit tests has no tsvector

    sql = text("""
        SELECT c.id
        FROM rag_chunks c
        JOIN rag_documents d ON d.id = c.document_id
        WHERE d.user_id = :uid
          AND d.status = 'ready'
          AND c.content_tsv @@ websearch_to_tsquery('english', :q)
        ORDER BY ts_rank(c.content_tsv, websearch_to_tsquery('english', :q)) DESC
        LIMIT :lim
    """)
    try:
        return [row[0] for row in db.execute(sql, {"uid": user_id, "q": query, "lim": limit})]
    except Exception as e:
        # Keyword search is the optional half. If it fails, vector search still
        # answers; taking the whole query down would be a worse outcome.
        logger.warning(f"[RAG] Keyword search unavailable, using vectors only: {e}")
        return []


def _reciprocal_rank_fusion(*rankings: list[str]) -> dict[str, float]:
    """Fuse several ranked id lists into one score per id."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def retrieve_relevant_chunks(user_id: str, query: str, top_k: int = TOP_K, limit: int | None = None) -> list[dict]:
    """Find the chunks most relevant to the query, across this user's ready
    documents only.

    Hybrid: semantic similarity and keyword relevance are run separately and
    their rankings fused. Vectors alone miss exact strings — error codes, part
    numbers, version numbers, proper nouns — because embeddings place "Sev-1"
    and "Sev-2" almost on top of each other, which is exactly wrong when the
    user asked about one of them. Keyword search has the opposite blind spot:
    no synonyms, no paraphrase. Neither is reliable alone.

    Every returned chunk keeps a real cosine `similarity`, including ones only
    keyword search found, because callers threshold on it — corpus_agent and
    the chat path both do, and a fabricated score there would quietly change
    what they let through.
    """
    effective_k = limit if limit is not None else top_k

    with get_tenant_session(user_id) as db:
        vector_hits = _vector_candidates(db, user_id, query, CANDIDATE_POOL)
        keyword_ids = _keyword_candidates(db, user_id, query, CANDIDATE_POOL)

        similarity_by_id = dict(vector_hits)
        vector_ids = [cid for cid, _ in vector_hits]

        fused = _reciprocal_rank_fusion(vector_ids, keyword_ids)
        if not fused:
            return []

        ranked_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:effective_k]

        rows = (
            db.query(RagChunk, RagDocument.filename)
            .join(RagDocument, RagChunk.document_id == RagDocument.id)
            .filter(RagChunk.id.in_(ranked_ids))
            .all()
        )
        by_id = {chunk.id: (chunk, filename) for chunk, filename in rows}

        # A chunk only keyword search surfaced has no similarity from the pool
        # above, so it is measured rather than guessed.
        missing = [cid for cid in ranked_ids if cid in by_id and cid not in similarity_by_id]
        if missing:
            query_vector = embed_query(query)
            distance = RagChunk.embedding.cosine_distance(query_vector)
            for cid, dist in (
                db.query(RagChunk.id, distance.label("distance"))
                .filter(RagChunk.id.in_(missing))
                .all()
            ):
                similarity_by_id[cid] = max(0.0, min(1.0, 1.0 - float(dist)))

        out = []
        for cid in ranked_ids:
            if cid not in by_id:
                continue
            chunk, filename = by_id[cid]
            out.append({
                "content": chunk.content,
                "filename": filename,
                "chunk_index": chunk.chunk_index,
                "similarity": similarity_by_id.get(cid, 0.0),
                "fusion_score": round(fused[cid], 5),
                "matched_by": (
                    "both" if cid in similarity_by_id and cid in keyword_ids
                    else "keyword" if cid in keyword_ids
                    else "vector"
                ),
            })
        return out


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
