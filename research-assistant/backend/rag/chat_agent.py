import json
import logging
import re
import time
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from config import get_settings
from utils import invoke_with_retry, clean_llm_response
from rag.store import RagConversation, RagMessage, get_tenant_session
from rag.retrieval import retrieve_relevant_chunks

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_HISTORY_MESSAGES = 10  # last N messages included as conversation context

SYSTEM_PROMPT = """You are an advanced AI research assistant. Answer questions using ONLY the
provided document excerpts.
Rules:
- Base your answer strictly on the excerpts given below.
- If the excerpts don't contain the answer, say so plainly instead of guessing.
- Cite the source filename inline when referencing a specific fact, like (source: report.pdf).
- Provide structured, high-clarity answers with bullet points when applicable.
"""

JUDGE_SYSTEM_PROMPT = """You are a strict grading system auditing a RAG (retrieval-augmented
generation) answer. Given source excerpts, a question, and a generated answer, score:
- faithfulness (0.0-1.0): does every factual claim in the answer trace back to the excerpts,
  with nothing invented or added from outside knowledge?
- relevance (0.0-1.0): does the answer actually address the question that was asked?
Give an overall verdict of PASS (faithful and relevant), PARTIAL (partially grounded or
incomplete), or FAIL (unsupported or off-topic), plus one short sentence of reasoning."""


GRADE_SYSTEM_PROMPT = """You decide whether a set of retrieved document excerpts is
sufficient to answer a question. Be strict: excerpts that are merely on the same broad
topic are NOT sufficient — they must actually contain the information asked for.
If they are insufficient, say what is missing in a few words."""

REWRITE_SYSTEM_PROMPT = """You rewrite a search query to retrieve better results from a
vector store of the user's own documents. Produce ONE alternative phrasing that uses
different, more specific wording — synonyms, likely section headings, or the concrete
terms a document would actually use. Output only the rewritten query, nothing else."""

CONTEXTUALIZE_SYSTEM_PROMPT = """Rewrite the user's latest message into a standalone search
query, resolving pronouns and references using the conversation so far. If it is already
standalone, return it unchanged. Output only the query, nothing else."""

# Above this cosine similarity the top hit is trusted without spending an LLM
# call to grade it. Retrieval quality is already measured, so the grader is
# only worth paying for when the numbers are ambiguous.
STRONG_MATCH_SIMILARITY = 0.78


class RetrievalGrade(BaseModel):
    sufficient: bool = Field(default=True)
    missing: str = Field(default="", description="What the excerpts fail to cover.")


class JudgeVerdict(BaseModel):
    faithfulness: float = Field(default=0.5, ge=0.0, le=1.0)
    relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    verdict: str = Field(default="PARTIAL", description="One of PASS, PARTIAL, FAIL.")
    reasoning: str = Field(default="", description="One short sentence explaining the verdict.")


def chat(
    user_id: str,
    conversation_id: str | None,
    message: str,
    top_k: int = 4,
    temperature: float = 0.2,
    similarity_threshold: float = 0.55,
) -> dict:
    start_time = time.time()
    try:
        with get_tenant_session(user_id) as db:
            conversation = _get_or_create_conversation(db, user_id, conversation_id)

            history = (
                db.query(RagMessage)
                .filter(RagMessage.conversation_id == conversation.id)
                .order_by(RagMessage.created_at.asc())
                .all()
            )

            # Agentic retrieval: resolves follow-up phrasing against the
            # conversation, grades whether what came back actually supports the
            # question, and rewrites its own query to try again if it doesn't.
            final_chunks, was_reranked, retrieval_trace = agentic_retrieve(
                user_id, message, history, top_k, similarity_threshold
            )
            context = _format_context(final_chunks)

            llm = ChatGroq(
                model=settings.groq_model_smart,
                api_key=settings.groq_api_key,
                temperature=temperature,
                max_tokens=1024,
            )

            messages = [SystemMessage(content=SYSTEM_PROMPT)]
            for msg in history[-MAX_HISTORY_MESSAGES:]:
                messages.append(
                    AIMessage(content=msg.content) if msg.role == "assistant" else HumanMessage(content=msg.content)
                )
            messages.append(HumanMessage(content=f"Document excerpts:\n{context}\n\nQuestion: {message}"))

            if not final_chunks:
                # Zero candidates *before* threshold filtering means the
                # corpus itself is empty, not merely unhelpful.
                saw_any_candidate = any(
                    t.get("candidates", 0) > 0 for t in retrieval_trace if t["step"] == "retrieve"
                )
                if not saw_any_candidate:
                    answer = "I don't have any documents to search yet — upload one first, then ask me about it."
                else:
                    answer = (
                        "I searched your documents — including a reworded second attempt — but "
                        "nothing in them supports this question well enough for me to answer "
                        "confidently. Try rephrasing, or lower the similarity threshold in "
                        "AI Parameter Tuning."
                    )
                sources = []
                judge = None
            else:
                response = invoke_with_retry(llm, messages)
                answer = clean_llm_response(response.content)
                sources = [
                    {
                        "filename": c["filename"],
                        "chunk_index": c["chunk_index"],
                        "base_similarity": round(c["similarity"], 3),
                        "rerank_score": round(c.get("rerank_score", c["similarity"]), 3),
                    }
                    for c in final_chunks
                ]
                judge = _judge_answer(message, context, answer)

            latency_ms = int((time.time() - start_time) * 1000)

            # Precision is now measured over what the loop actually settled on.
            attempts = [t for t in retrieval_trace if t["step"] == "retrieve"]
            context_precision = round(
                len(final_chunks) / max(top_k, 1), 3
            ) if final_chunks else 0.0

            # Engineering telemetry for the AI Inspector / Reranking panel — every
            # value here is either measured directly or the honest absence of a
            # measurement (None), never a fabricated placeholder.
            telemetry = {
                "faithfulness_score": judge["faithfulness"] if judge else None,
                "answer_relevance": judge["relevance"] if judge else None,
                "context_precision": context_precision,
                "latency_ms": latency_ms,
                "chunks_retrieved": max((t.get("found", 0) for t in attempts), default=0),
                "chunks_used": len(final_chunks),
                "similarity_threshold": similarity_threshold,
                "temperature": temperature,
                "model": settings.groq_model_smart,
                "reranked": was_reranked,
                "retrieval_trace": retrieval_trace,
                "retrieval_attempts": len(attempts),
                "self_corrected": any(t["step"] == "rewrite" for t in retrieval_trace),
                "llm_judge": {
                    "verdict": judge["verdict"] if judge else "NOT EVALUATED",
                    "reasoning": judge["reasoning"] if judge else "The judge model was not run for this response.",
                    "eval_model": settings.groq_model_fast,
                    "available": judge is not None,
                } if final_chunks else None,
                "reranked_chunks": [
                    {
                        "filename": c["filename"],
                        "chunk_index": c["chunk_index"],
                        "base_similarity": round(c["similarity"], 3),
                        "rerank_score": round(c.get("rerank_score", c["similarity"]), 3),
                    }
                    for c in final_chunks
                ],
            }

            db.add(RagMessage(conversation_id=conversation.id, role="user", content=message))
            db.add(RagMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=answer,
                sources=json.dumps(sources),
            ))
            db.commit()

            return {
                "conversation_id": conversation.id,
                "answer": answer,
                "sources": sources,
                "telemetry": telemetry,
            }
    except Exception as e:
        logger.error(f"[RAGChat] Error: {e}")
        return {
            "conversation_id": conversation_id or "",
            "answer": "Sorry, something went wrong processing that inquiry.",
            "sources": [],
            "telemetry": None,
        }


def list_conversations(user_id: str) -> list[dict]:
    """List all RAG conversations for a user with titles and message counts."""
    with get_tenant_session(user_id) as db:
        convs = (
            db.query(RagConversation)
            .filter(RagConversation.user_id == user_id)
            .order_by(RagConversation.created_at.desc())
            .all()
        )
        result = []
        for c in convs:
            first_msg = (
                db.query(RagMessage)
                .filter(RagMessage.conversation_id == c.id, RagMessage.role == "user")
                .order_by(RagMessage.created_at.asc())
                .first()
            )
            msg_count = db.query(RagMessage).filter(RagMessage.conversation_id == c.id).count()
            title = first_msg.content[:60] + "…" if first_msg and len(first_msg.content) > 60 else (first_msg.content if first_msg else "New Conversation")
            result.append({
                "id": c.id,
                "title": title,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "message_count": msg_count,
            })
        return result


def delete_conversation(conversation_id: str, user_id: str) -> bool:
    """Delete a specific RAG conversation and its messages."""
    with get_tenant_session(user_id) as db:
        conv = (
            db.query(RagConversation)
            .filter(RagConversation.id == conversation_id, RagConversation.user_id == user_id)
            .first()
        )
        if not conv:
            return False
        db.delete(conv)
        db.commit()
        return True


def get_conversation_history(conversation_id: str, user_id: str) -> list[dict]:
    with get_tenant_session(user_id) as db:
        conversation = (
            db.query(RagConversation)
            .filter(RagConversation.id == conversation_id, RagConversation.user_id == user_id)
            .first()
        )
        if not conversation:
            return []

        messages = (
            db.query(RagMessage)
            .filter(RagMessage.conversation_id == conversation_id)
            .order_by(RagMessage.created_at.asc())
            .all()
        )
        return [
            {
                "role": m.role,
                "content": m.content,
                "sources": json.loads(m.sources) if m.sources else [],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]


def _get_or_create_conversation(db, user_id: str, conversation_id: str | None) -> RagConversation:
    if conversation_id:
        existing = (
            db.query(RagConversation)
            .filter(RagConversation.id == conversation_id, RagConversation.user_id == user_id)
            .first()
        )
        if existing:
            return existing
    conversation = RagConversation(user_id=user_id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _fast_llm() -> ChatGroq:
    """Small model for the loop's control decisions. These are short structural
    judgements, not synthesis — paying 120B rates for them would eat the token
    budget that the answer itself needs."""
    return ChatGroq(model=settings.groq_model_fast, api_key=settings.groq_api_key, temperature=0.0)


def _one_line(llm, system: str, user: str, fallback: str) -> str:
    """Run a prompt expected to return a single short line, falling back to the
    original text rather than failing the whole turn."""
    try:
        response = invoke_with_retry(llm, [SystemMessage(content=system), HumanMessage(content=user)])
        text = clean_llm_response(str(getattr(response, "content", response))).strip().strip('"')
        first = text.splitlines()[0].strip() if text else ""
        return first or fallback
    except Exception as e:
        logger.debug(f"[RAGChat] one-line prompt fell back: {e}")
        return fallback


def _grade_retrieval(llm, question: str, chunks: list[dict]) -> tuple[bool, str]:
    """Decide whether these excerpts can actually answer the question."""
    if not chunks:
        return False, "nothing retrieved"
    excerpts = "\n\n".join(f"[{c['filename']}]\n{c['content'][:700]}" for c in chunks[:4])
    user = f"Question: {question}\n\nRetrieved excerpts:\n{excerpts}"
    try:
        result = invoke_with_retry(llm.with_structured_output(RetrievalGrade), [
            SystemMessage(content=GRADE_SYSTEM_PROMPT), HumanMessage(content=user)])
        if isinstance(result, RetrievalGrade):
            return bool(result.sufficient), result.missing
        if isinstance(result, dict):
            return bool(result.get("sufficient", True)), str(result.get("missing", ""))
    except Exception as e:
        logger.debug(f"[RAGChat] Retrieval grading unavailable, accepting hits: {e}")
    # If the grader can't run, don't block the answer on it.
    return True, ""


def agentic_retrieve(
    user_id: str, message: str, history: list, top_k: int, similarity_threshold: float
) -> tuple[list[dict], bool, list[dict]]:
    """Retrieve with the ability to reconsider.

    Unlike a single-shot lookup this can rewrite its own query and try again
    when the first attempt doesn't actually support the question, and it
    resolves follow-up phrasing ("what about the second one?") against the
    conversation before searching. Returns the chosen chunks, whether a real
    cross-encoder rerank happened, and a step-by-step trace for the UI.
    """
    trace: list[dict] = []
    llm = _fast_llm()

    # Step 1 — resolve references so a follow-up doesn't search for pronouns.
    search_query = message
    if history:
        recent = "\n".join(f"{m.role}: {m.content[:300]}" for m in history[-4:])
        rewritten = _one_line(llm, CONTEXTUALIZE_SYSTEM_PROMPT,
                              f"Conversation so far:\n{recent}\n\nLatest message: {message}", message)
        if rewritten != message:
            search_query = rewritten
            trace.append({"step": "contextualize", "query": rewritten,
                          "note": "resolved against conversation history"})

    best: tuple[list[dict], bool] = ([], False)
    for attempt in range(2):
        candidates = retrieve_relevant_chunks(user_id, search_query, top_k=max(top_k, 6))
        selected, reranked = _select_chunks(search_query, candidates, top_k, similarity_threshold)
        top_sim = round(max((c["similarity"] for c in candidates), default=0.0), 3)

        if len(selected) > len(best[0]):
            best = (selected, reranked)

        # Cheap gate: a strong cosine hit doesn't need an LLM opinion.
        if selected and selected[0]["similarity"] >= STRONG_MATCH_SIMILARITY:
            trace.append({"step": "retrieve", "query": search_query, "found": len(selected),
                          "candidates": len(candidates),
                          "top_similarity": top_sim, "verdict": "strong match — accepted"})
            return selected, reranked, trace

        sufficient, missing = _grade_retrieval(llm, message, selected)
        trace.append({"step": "retrieve", "query": search_query, "found": len(selected),
                      "candidates": len(candidates), "top_similarity": top_sim,
                      "verdict": "sufficient" if sufficient else f"insufficient — {missing or 'no useful match'}"})

        if sufficient and selected:
            return selected, reranked, trace
        if attempt == 0:
            # Step 2 — rewrite and try once more before giving up.
            search_query = _one_line(
                llm, REWRITE_SYSTEM_PROMPT,
                f"Original query: {search_query}\nWhy it failed: {missing or 'no relevant excerpts found'}",
                search_query)
            trace.append({"step": "rewrite", "query": search_query,
                          "note": "retrying with different wording"})

    if best[0]:
        trace.append({"step": "best_effort",
                      "note": f"no attempt graded sufficient — answering from the closest {len(best[0])} chunk(s)"})
    else:
        trace.append({"step": "give_up", "note": "no attempt produced supporting evidence"})
    return best[0], best[1], trace


def _select_chunks(
    query: str, candidates: list[dict], top_k: int, similarity_threshold: float
) -> tuple[list[dict], bool]:
    """Filter retrieved chunks by real cosine similarity, then optionally
    re-rank the survivors with a real cross-encoder (Cohere) when configured.
    Falls back to plain similarity ordering — which pgvector already
    guarantees — when Cohere isn't configured or the call fails.
    Returns (selected_chunks, whether_a_real_rerank_happened)."""
    above_threshold = [c for c in candidates if c["similarity"] >= similarity_threshold]

    if not above_threshold:
        return [], False

    if len(above_threshold) <= top_k or not settings.cohere_api_key:
        return above_threshold[:top_k], False

    try:
        from langchain_cohere import CohereRerank
        from langchain_core.documents import Document

        docs = [
            Document(page_content=c["content"], metadata={"idx": i})
            for i, c in enumerate(above_threshold)
        ]
        reranker = CohereRerank(
            cohere_api_key=settings.cohere_api_key,
            model="rerank-english-v3.0",
            top_n=top_k,
        )
        ranked = reranker.compress_documents(documents=docs, query=query)
        selected = []
        for doc in ranked:
            chunk = dict(above_threshold[doc.metadata["idx"]])
            chunk["rerank_score"] = float(doc.metadata.get("relevance_score", chunk["similarity"]))
            selected.append(chunk)
        return selected, True
    except Exception as e:
        logger.warning(f"[RAGChat] Cohere rerank failed, using similarity order: {e}")
        return above_threshold[:top_k], False


def _judge_answer(question: str, context: str, answer: str) -> dict | None:
    """Ask a fast model to grade the generated answer against the retrieved
    context. Returns None — rather than a fabricated score — if the judge
    call fails outright, so callers can be honest about it not having run."""
    human_content = f"Question: {question}\n\nSource excerpts:\n{context[:4000]}\n\nGenerated answer:\n{answer}"
    llm = ChatGroq(model=settings.groq_model_fast, api_key=settings.groq_api_key, temperature=0.0)

    try:
        structured_llm = llm.with_structured_output(JudgeVerdict)
        result = invoke_with_retry(structured_llm, [
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=human_content),
        ])
        if isinstance(result, JudgeVerdict):
            return result.model_dump()
        if isinstance(result, dict):
            return JudgeVerdict(**result).model_dump()
    except Exception as e:
        logger.debug(f"[RAGChat] Judge structured output fallback: {e}")

    try:
        json_prompt = (
            JUDGE_SYSTEM_PROMPT
            + '\nRespond with JSON only: {"faithfulness": 0.0-1.0, "relevance": 0.0-1.0, '
              '"verdict": "PASS|PARTIAL|FAIL", "reasoning": "..."}'
        )
        response = invoke_with_retry(llm, [
            SystemMessage(content=json_prompt),
            HumanMessage(content=human_content),
        ])
        raw = clean_llm_response(str(getattr(response, "content", response)))
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return JudgeVerdict(**json.loads(match.group(0))).model_dump()
    except Exception as e:
        logger.warning(f"[RAGChat] LLM-as-a-Judge evaluation failed: {e}")

    return None


def _format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "No documents available."
    parts = []
    for c in chunks:
        parts.append(f"[{c['filename']} — chunk {c['chunk_index']}]\n{c['content']}")
    return "\n\n".join(parts)
