from langchain_groq import ChatGroq
from langchain_cohere import CohereRerank
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.documents import Document
from config import get_settings
from graph.state import ResearchState
from utils import invoke_with_retry, clean_llm_response
from rag.ingest import chunk_text
import logging

logger = logging.getLogger(__name__)
settings = get_settings()

CHUNK_SIZE = 800
# Chunks were previously sliced with no overlap at all, mid-word, so any
# statistic or claim straddling an 800-character boundary became two unusable
# halves — in the exact path that produces the report. rag/ingest.py already
# had this right; this brings the analyst in line with it.
CHUNK_OVERLAP = 120
TOP_K_CHUNKS = 10


# =============================================
# ANALYST AGENT
# Synthesizes all source documents into a draft answer
# Uses the smarter Groq model for deep reasoning
# =============================================

SYSTEM_PROMPT = """You are an expert research analyst. Synthesize the provided
sources into a clear, accurate answer for a reader who is new to the topic.

- Draw across ALL the sources; don't summarise one and stop.
- Explain each idea in full sentences. A term needs a sentence saying what it is
  and why it matters, not a two-word definition — the reader cannot look it up
  from a fragment.
- Say why a fact matters, not only that it is true.
- Where sources disagree, say so and give both readings.
- Cite by title or URL at the specific claim it supports.
- Use concrete numbers, dates and names wherever the sources provide them.
- Markdown for structure. Reach for a table only when comparing several things
  across the same dimensions; if the cells would be sentence fragments, write
  paragraphs instead.
- Skip throat-clearing. Start with the answer.
"""


def analyst_agent(state: ResearchState) -> ResearchState:
    logger.info(f"[AnalystAgent] Synthesizing {len(state['source_documents'])} documents")

    if not state["source_documents"]:
        return {
            **state,
            "draft_answer": "Could not find sufficient sources to answer this question.",
            "current_step": "analysis_done",
            "error": "No source documents available",
        }

    # Build context from the chunks most relevant to the query (Cohere rerank),
    # instead of naively concatenating every source's raw text.
    context = build_context(state["query"], state["source_documents"])

    llm = ChatGroq(
        model=settings.groq_model_smart,    # strongest available — deep reasoning
        api_key=settings.groq_api_key,
        temperature=0.2,                    # low temp = more factual
        max_tokens=2048,
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"""
Research Question: {state["query"]}

Sources:
{context}

Please provide a comprehensive, well-structured answer based on these sources.
"""),
    ]

    try:
        response = invoke_with_retry(llm, messages)
        draft = clean_llm_response(response.content)
        logger.info("[AnalystAgent] Draft answer generated successfully")

        return {
            **state,
            "draft_answer": draft,
            "current_step": "analysis_done",
        }

    except Exception as e:
        logger.error(f"[AnalystAgent] Error: {e}")
        return {
            **state,
            "draft_answer": "",
            "current_step": "analysis_done",
            "error": str(e),
        }


def chunk_documents(documents: list) -> list[Document]:
    """Split each source document into overlapping chunks for retrieval,
    keeping provenance (title/url) attached to every chunk.

    Splitting is delegated to rag.ingest.chunk_text so the research path and
    the document-upload path cannot drift apart on chunking behaviour again.
    """
    chunks = []
    for doc in documents:
        for piece in chunk_text(doc["text"], chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
            chunks.append(Document(
                page_content=piece,
                metadata={
                    "title": doc["title"],
                    "url": doc["url"],
                    "origin": doc.get("origin", "web"),
                },
            ))
    return chunks


# Slots held for the user's own uploaded documents. Without a floor they lose
# every time: web search returns dozens of pages, corpus documents are appended
# last, and the unreranked path simply takes the first TOP_K_CHUNKS — so a
# document the user deliberately uploaded would never reach the analyst.
RESERVED_CORPUS_CHUNKS = 4


def _rank_chunks(query: str, chunks: list, top_k: int) -> list:
    """Return the top_k chunks most relevant to the query.

    Uses Cohere rerank when a key is configured and there is something to
    choose between; otherwise falls back to the leading chunks, which is the
    best available ordering without a relevance signal.
    """
    if not chunks or top_k <= 0:
        return []
    if len(chunks) <= top_k or not settings.cohere_api_key:
        return chunks[:top_k]

    try:
        reranker = CohereRerank(
            cohere_api_key=settings.cohere_api_key,
            model="rerank-english-v3.0",
            top_n=top_k,
        )
        return list(reranker.compress_documents(documents=chunks, query=query))
    except Exception as e:
        logger.warning(f"[AnalystAgent] Cohere rerank failed, using first {top_k} chunks: {e}")
        return chunks[:top_k]


def build_context(query: str, documents: list) -> str:
    """Rank all source chunks by relevance to the query and keep only the
    top-K, so the analyst sees the most relevant material instead of the first
    N characters of each source.

    Chunks from the user's own corpus are ranked separately and guaranteed a
    share of the context: they were chosen deliberately, so they should not
    have to out-compete forty scraped pages for a place."""
    all_chunks = chunk_documents(documents)

    if not all_chunks:
        return "No content available."

    corpus_chunks = [c for c in all_chunks if c.metadata.get("origin") == "corpus"]
    web_chunks = [c for c in all_chunks if c.metadata.get("origin") != "corpus"]

    # Both pools are ranked. The corpus pool used to be sliced with
    # corpus_chunks[:4] — the first four in insertion order, which for an
    # uploaded paper means its title page and abstract boilerplate rather than
    # the passages that answer the question. "Reserved" is about guaranteeing
    # the slots, not about skipping the ranking.
    kept_corpus = _rank_chunks(query, corpus_chunks, RESERVED_CORPUS_CHUNKS)
    web_budget = max(TOP_K_CHUNKS - len(kept_corpus), 1)
    ranked_web = _rank_chunks(query, web_chunks, web_budget)

    # The user's documents lead the context, so they are the first thing the
    # analyst reads rather than a footnote after forty web pages.
    ranked_chunks = kept_corpus + ranked_web
    if kept_corpus:
        logger.info(
            f"[AnalystAgent] Context: {len(kept_corpus)} chunk(s) from the user's documents "
            f"+ {len(ranked_web)} from the web"
        )

    parts = []
    for i, chunk in enumerate(ranked_chunks, 1):
        parts.append(f"""
--- Source {i}: {chunk.metadata['title']} ---
URL: {chunk.metadata['url']}
Content:
{chunk.page_content}
""")
    return "\n".join(parts)
