"""Corpus agent — searches the user's own uploaded documents.

This is what connects the two halves of the product. "Deep Research" gathers
from the open web; "Chat with Files" indexes documents the user uploaded. Until
this node existed they were separate features that never met, and the research
pipeline could not cite a paper the user had given it.

The node runs on every pass, including when web search returned nothing: the
answer may well be sitting in the user's own files.
"""

import logging

from graph.state import ResearchState
from rag.retrieval import retrieve_relevant_chunks

logger = logging.getLogger(__name__)

# Chunks pulled per sub-query. Kept modest because these are concatenated into
# the analyst's context alongside the web documents.
CHUNKS_PER_QUERY = 4

# Corpus hits are held to a higher bar than the chat path: here they compete
# with full web pages for space in the analyst's context, so a marginal match
# is worse than no match.
MIN_SIMILARITY = 0.60


def corpus_agent(state: ResearchState) -> ResearchState:
    user_id = state.get("user_id")
    existing = list(state.get("source_documents", []))

    if not user_id:
        # Unauthenticated paths (the run.py smoke script) have no tenant to
        # search. Not an error — just nothing to add.
        return {**state, "current_step": "corpus_done"}

    queries = state.get("sub_queries") or [state["query"]]
    already_added = {d["url"] for d in existing if d.get("origin") == "corpus"}
    seen: set[tuple[str, int]] = set()
    by_document: dict[str, list[tuple[int, str, float]]] = {}

    for sub_query in queries:
        try:
            chunks = retrieve_relevant_chunks(user_id, sub_query, top_k=CHUNKS_PER_QUERY)
        except Exception as e:
            logger.warning(f"[CorpusAgent] Retrieval failed for '{sub_query[:40]}': {e}")
            continue

        for chunk in chunks:
            if chunk["similarity"] < MIN_SIMILARITY:
                continue
            key = (chunk["filename"], chunk["chunk_index"])
            if key in seen:
                continue
            seen.add(key)
            by_document.setdefault(chunk["filename"], []).append(
                (chunk["chunk_index"], chunk["content"], chunk["similarity"])
            )

    if not by_document:
        logger.info("[CorpusAgent] No uploaded documents matched this query")
        return {**state, "current_step": "corpus_done"}

    # One SourceDocument per file, with its matching passages stitched back
    # into reading order — the analyst and fact-checker both expect a document,
    # not a bag of fragments.
    corpus_docs = []
    for filename, pieces in by_document.items():
        if f"upload://{filename}" in already_added:
            continue  # the reflective loop already attached this file
        pieces.sort(key=lambda p: p[0])
        best = max(p[2] for p in pieces)
        corpus_docs.append({
            "url": f"upload://{filename}",
            "title": f"{filename} (your document)",
            "text": "\n\n".join(text for _, text, _ in pieces),
            "origin": "corpus",
        })
        logger.info(
            f"[CorpusAgent] ✓ {filename}: {len(pieces)} passage(s), best match {best:.2f}"
        )

    logger.info(
        f"[CorpusAgent] Added {len(corpus_docs)} document(s) from the user's knowledge base"
    )
    return {
        **state,
        "source_documents": existing + corpus_docs,
        "current_step": "corpus_done",
    }
