"""Finding the moments in a transcript that bear on a question.

Hybrid, because neither half is reliable alone. Embeddings put "shut it down"
and "start it up" close together — they are used in identical contexts and mean
opposite things. Keyword search has no notion of paraphrase, so a question about
"restarting" finds nothing in a transcript that says "power cycling".

The rankings are fused by Reciprocal Rank Fusion rather than by score, because
cosine distance and ts_rank are different scales with no meaningful conversion
between them. Normalising one onto the other would invent a relationship, and
the invented relationship would then silently decide which passages the answer
gets written from.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.ingest.embed import embed_query

log = logging.getLogger("analysis.retrieve")

CANDIDATE_POOL = 20
RRF_K = 60


def retrieve(session, media_id: str, question: str, *,
             limit: int = 6) -> list[dict]:
    """The passages most likely to answer `question`, each with its timestamp."""
    vector = embed_query(question)

    vector_hits = session.execute(text("""
        SELECT id, ordinal, start_ms, end_ms, text, confidence
        FROM transcript_chunks
        WHERE media_id = :media_id AND embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:v AS vector)
        LIMIT :pool
    """), {"media_id": media_id, "v": str(vector), "pool": CANDIDATE_POOL}).all()

    try:
        keyword_hits = session.execute(text("""
            SELECT id, ordinal, start_ms, end_ms, text, confidence
            FROM transcript_chunks
            WHERE media_id = :media_id
              AND to_tsvector('english', text)
                  @@ websearch_to_tsquery('english', :q)
            ORDER BY ts_rank(to_tsvector('english', text),
                             websearch_to_tsquery('english', :q)) DESC
            LIMIT :pool
        """), {"media_id": media_id, "q": question,
               "pool": CANDIDATE_POOL}).all()
    except Exception as exc:
        # websearch_to_tsquery rejects some inputs outright. Degrading to the
        # vector half is a worse answer; failing the request is no answer.
        log.info("[retrieve] keyword half unavailable, using vectors only: %s", exc)
        keyword_hits = []

    scores: dict[str, float] = {}
    rows: dict[str, tuple] = {}
    for ranking in (vector_hits, keyword_hits):
        for rank, row in enumerate(ranking, start=1):
            scores[row.id] = scores.get(row.id, 0.0) + 1.0 / (RRF_K + rank)
            rows[row.id] = row

    best = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    out = []
    for chunk_id, score in best:
        r = rows[chunk_id]
        out.append({
            "ordinal": r.ordinal,
            "start_ms": r.start_ms,
            "end_ms": r.end_ms,
            "text": r.text,
            "confidence": r.confidence,
            "score": round(score, 6),
        })
    return out
