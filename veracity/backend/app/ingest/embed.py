"""Embedding chunks, locally.

Local rather than hosted for one reason that shapes everything else: it costs
nothing per call. Retrieval over a two-hour transcript can be run as often as
you like, and evaluating it over hundreds of questions is free. A per-query fee
turns measurement into something you do once and quote forever.

The model is asymmetric — it expects a query to carry an instruction prefix that
a passage does not. Getting that backwards degrades retrieval silently: results
still come back and still look plausible, so nothing fails and the quality just
quietly drops. The prefix is applied at query time only, in one place.
"""
from __future__ import annotations

import logging
import threading

from app.config import settings

log = logging.getLogger("ingest.embed")

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_model = None
_lock = threading.Lock()


def _load():
    """Load once per process, under a lock.

    Loading is seconds and several hundred megabytes. Two worker threads racing
    into it would do both twice.
    """
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding
                log.info("[embed] loading %s", settings().embedding_model)
                _model = TextEmbedding(model_name=settings().embedding_model)
                log.info("[embed] ready")
    return _model


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Vectors for text being stored. No prefix."""
    if not texts:
        return []
    return [v.tolist() for v in _load().embed(texts)]


def embed_query(text: str) -> list[float]:
    """A vector for text being searched with. Prefixed."""
    return next(iter(_load().embed([QUERY_PREFIX + text]))).tolist()
