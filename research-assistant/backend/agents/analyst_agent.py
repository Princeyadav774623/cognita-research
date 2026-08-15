from langchain_groq import ChatGroq
from langchain_cohere import CohereRerank
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.documents import Document
from config import get_settings
from graph.state import ResearchState
from utils import invoke_with_retry
import logging

logger = logging.getLogger(__name__)
settings = get_settings()

CHUNK_SIZE = 800
TOP_K_CHUNKS = 10


# =============================================
# ANALYST AGENT
# Synthesizes all source documents into a draft answer
# Uses the smarter Groq model for deep reasoning
# =============================================

SYSTEM_PROMPT = """You are an expert research analyst. Your job is to synthesize information
from multiple sources and produce a comprehensive, accurate answer to a research question.

Rules:
- Synthesize across ALL provided sources, don't just summarize one
- Cite sources by their title or URL when making specific claims
- Structure your answer with clear sections
- Be thorough but concise
- If sources contradict each other, mention both perspectives
- Use markdown formatting for headers and lists
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
        model=settings.groq_model_smart,   # llama-3.3-70b-versatile — best reasoning
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
        draft = response.content.strip()
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
    """Split each source document into smaller chunks for retrieval, keeping
    provenance (title/url) attached to every chunk."""
    chunks = []
    for doc in documents:
        text = doc["text"]
        for start in range(0, len(text), CHUNK_SIZE):
            piece = text[start:start + CHUNK_SIZE].strip()
            if piece:
                chunks.append(Document(
                    page_content=piece,
                    metadata={"title": doc["title"], "url": doc["url"]},
                ))
    return chunks


def build_context(query: str, documents: list) -> str:
    """Rank all source chunks by relevance to the query with Cohere rerank
    and keep only the top-K, so the analyst sees the most relevant material
    instead of the first N characters of each source."""
    chunks = chunk_documents(documents)

    if not chunks:
        return "No content available."

    ranked_chunks = chunks
    if len(chunks) > TOP_K_CHUNKS and settings.cohere_api_key:
        try:
            reranker = CohereRerank(
                cohere_api_key=settings.cohere_api_key,
                model="rerank-english-v3.0",
                top_n=TOP_K_CHUNKS,
            )
            ranked_chunks = reranker.compress_documents(documents=chunks, query=query)
        except Exception as e:
            logger.warning(f"[AnalystAgent] Cohere rerank failed, using first {TOP_K_CHUNKS} chunks: {e}")
            ranked_chunks = chunks[:TOP_K_CHUNKS]
    else:
        ranked_chunks = chunks[:TOP_K_CHUNKS]

    parts = []
    for i, chunk in enumerate(ranked_chunks, 1):
        parts.append(f"""
--- Source {i}: {chunk.metadata['title']} ---
URL: {chunk.metadata['url']}
Content:
{chunk.page_content}
""")
    return "\n".join(parts)
