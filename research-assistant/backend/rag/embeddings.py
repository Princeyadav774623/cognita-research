from functools import lru_cache
import logging

logger = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-small-en-v1.5"  # 384-dim, matches EMBEDDING_DIM in store.py

# BGE is trained asymmetrically: queries carry a retrieval instruction, stored
# passages do not. Embedding both sides identically — which is what this module
# used to do — throws away the distinction the model was trained to exploit and
# measurably costs recall on short queries.
#
# Only embed_query() applies this. Passages stay bare, so the vectors already in
# rag_chunks remain correct and nothing needs re-indexing.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@lru_cache()
def _get_embedder():
    from fastembed import TextEmbedding
    logger.info(f"[Embeddings] Loading local embedding model: {MODEL_NAME}")
    return TextEmbedding(model_name=MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of passages locally (no external API call).

    Passage-side embedding: no instruction prefix. Use embed_query() for the
    query side.
    """
    embedder = _get_embedder()
    return [vec.tolist() for vec in embedder.embed(texts)]


def embed_query(query: str) -> list[float]:
    """Embed a search query, with the instruction prefix BGE expects."""
    return embed_texts([QUERY_INSTRUCTION + query])[0]
