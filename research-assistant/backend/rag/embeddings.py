from functools import lru_cache
import logging

logger = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-small-en-v1.5"  # 384-dim, matches EMBEDDING_DIM in store.py


@lru_cache()
def _get_embedder():
    from fastembed import TextEmbedding
    logger.info(f"[Embeddings] Loading local embedding model: {MODEL_NAME}")
    return TextEmbedding(model_name=MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts locally (no external API call)."""
    embedder = _get_embedder()
    return [vec.tolist() for vec in embedder.embed(texts)]


def embed_query(query: str) -> list[float]:
    return embed_texts([query])[0]
