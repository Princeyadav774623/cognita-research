"""Evidence selection for claim verification.

The fact-checker used to build its evidence block positionally: the first 1,000
characters of each source document, joined, then cut to 6,000 characters total.
On a run that gathered 40 sources that is roughly the top of the first six —
so a claim the analyst drew from source 20, or from the middle of source 3, had
no supporting text in the window at all and came back "unverified" for reasons
that had nothing to do with whether it was true.

This module selects evidence by relevance to the specific claim instead, out of
every chunk of every source. Scoring is deliberately local and lexical rather
than another model call: verification already sits on the critical path, and a
claim and its supporting sentence share proper nouns, numbers and terms of art,
which is exactly what overlap scoring is good at.
"""

import math
import re
from collections import Counter

# Words carrying no discriminating power. Kept short on purpose — an aggressive
# stoplist strips domain terms that happen to look common.
_STOPWORDS = frozenset("""
a an and are as at be been but by for from had has have in into is it its of on
or that the their they this to was were which with would can could may might
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


def _idf(chunks: list[str]) -> dict[str, float]:
    """Inverse document frequency across the candidate pool, so a term shared by
    every source (the topic word itself) counts for less than a term that
    appears in only the two chunks that actually discuss the claim."""
    n = len(chunks) or 1
    seen = Counter()
    for chunk in chunks:
        for term in set(tokenize(chunk)):
            seen[term] += 1
    return {term: math.log(1 + n / count) for term, count in seen.items()}


def score_chunk(claim_terms: Counter, chunk: str, idf: dict[str, float]) -> float:
    """Overlap between claim and chunk, weighted by term rarity and normalised
    for length so a long chunk doesn't win on volume alone."""
    chunk_terms = Counter(tokenize(chunk))
    if not chunk_terms:
        return 0.0
    overlap = sum(
        min(count, chunk_terms[term]) * idf.get(term, 1.0)
        for term, count in claim_terms.items()
        if term in chunk_terms
    )
    return overlap / math.sqrt(len(chunk_terms))


def chunk_document(text: str, size: int = 700, overlap: int = 100) -> list[str]:
    """Split a source into overlapping windows so a sentence spanning a
    boundary still appears whole in one of them."""
    text = (text or "").strip()
    if not text:
        return []
    pieces, start = [], 0
    while start < len(text):
        piece = text[start:start + size].strip()
        if piece:
            pieces.append(piece)
        if start + size >= len(text):
            break
        start += size - overlap
    return pieces


def select_evidence(
    claim: str,
    documents: list[dict],
    top_k: int = 4,
    chars_per_chunk: int = 700,
) -> list[dict]:
    """Return the passages most likely to settle this claim, drawn from every
    document rather than the first few.

    Each entry carries its provenance so the verifier can cite a real source
    and the caller can tell corroborating sources apart from the ones the draft
    was written from.
    """
    claim_terms = Counter(tokenize(claim))
    if not claim_terms:
        return []

    candidates: list[tuple[str, dict]] = []
    for doc in documents:
        for piece in chunk_document(doc.get("text", ""), size=chars_per_chunk):
            candidates.append((piece, doc))

    if not candidates:
        return []

    idf = _idf([text for text, _ in candidates])
    scored = [
        (score_chunk(claim_terms, text, idf), text, doc)
        for text, doc in candidates
    ]
    scored.sort(key=lambda row: row[0], reverse=True)

    selected: list[dict] = []
    seen_urls: set[str] = set()
    # One passage per source first, so four slots aren't spent on four windows
    # of the same page — agreement across sources is the signal that matters.
    for score, text, doc in scored:
        if score <= 0:
            break
        url = doc.get("url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        selected.append({
            "text": text,
            "title": doc.get("title", "Untitled"),
            "url": url,
            "origin": doc.get("origin", "web"),
            "score": round(score, 3),
        })
        if len(selected) >= top_k:
            break

    return selected
