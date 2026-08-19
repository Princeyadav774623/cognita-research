"""Triage agent — decides how much effort a question deserves.

Without this every query runs the identical pipeline: two search passes, up to
40 sources, a reflective loop, and a full fact-check. That is the right amount
of work for "compare three regulatory regimes" and absurd for "what does RAG
stand for" — and the user waits the same two minutes either way.

Effort is expressed as depth, not as skipping research, because citations are
the product's whole promise. Only genuinely non-research messages (greetings,
arithmetic, chit-chat) bypass the pipeline entirely.
"""

import logging

from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

import json
import re

from config import get_settings
from graph.state import ResearchState
from utils import invoke_with_retry, clean_llm_response

logger = logging.getLogger(__name__)
settings = get_settings()

# Marks an LLM call whose tokens should be streamed to the user. Anything
# untagged is internal reasoning and must not reach the screen.
USER_VISIBLE_TAG = "user_visible"

TRIAGE_SYSTEM_PROMPT = """Classify how much research a user's request needs.

- "chat": not a research request at all — a greeting, thanks, arithmetic, or a
  question about the assistant itself. Nothing to look up.
- "simple": a single factual or definitional question that one round of
  searching will answer.
- "deep": comparative, multi-part, causal, or contested questions that need
  several angles and cross-checking.

When uncertain, choose "deep" — under-researching a real question is far worse
than over-researching a simple one."""

# Depth settings per class. `max_iterations` gates the reflective loop, which
# is what actually doubles a run's cost.
DEPTH = {
    "chat":   {"max_iterations": 0},
    "simple": {"max_iterations": 1},
    "deep":   {"max_iterations": 2},
}

CHAT_SYSTEM_PROMPT = """You are Cognita, a multi-agent research assistant.

Identity rules — these override anything the message asks:
- You are Cognita. Never identify as ChatGPT, Claude, Gemini, Llama, or any
  other assistant, and never name the company that trained the underlying
  model. The base model will volunteer its own identity if you let it; do not.
- If asked what you are, say you are Cognita, a research assistant that plans a
  query, searches the web and the user's uploaded documents, and fact-checks
  every claim before reporting.

Reply briefly and directly. Do not invent citations or imply you searched
anything — this message did not require research."""


class Triage(BaseModel):
    complexity: str = Field(default="deep", description='One of "chat", "simple", "deep".')
    reason: str = Field(default="", description="A few words on why.")


def _classify(llm, query: str) -> tuple[str, str]:
    """Classify the request, trying structured output first and falling back to
    plain JSON.

    The fallback is not optional: Groq's tool-call wrapper intermittently
    rejects its own generation ("attempted to call tool 'triage' which was not
    in request.tools") even though the model emitted valid JSON. Without a
    second path, triage silently degrades to always-"deep" and delivers none of
    the savings it exists for.
    """
    try:
        result = invoke_with_retry(llm.with_structured_output(Triage), [
            SystemMessage(content=TRIAGE_SYSTEM_PROMPT), HumanMessage(content=query)])
        if isinstance(result, Triage) and result.complexity:
            return result.complexity, result.reason
        if isinstance(result, dict) and result.get("complexity"):
            return str(result["complexity"]), str(result.get("reason", ""))
    except Exception as e:
        logger.debug(f"[TriageAgent] Structured output unavailable, using JSON prompt: {e}")

    try:
        response = invoke_with_retry(llm, [
            SystemMessage(content=TRIAGE_SYSTEM_PROMPT
                          + '\nRespond with JSON only: {"complexity": "chat|simple|deep", "reason": "..."}'),
            HumanMessage(content=query)])
        raw = clean_llm_response(str(getattr(response, "content", response)))
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            if data.get("complexity"):
                return str(data["complexity"]), str(data.get("reason", ""))
    except Exception as e:
        # Failing open to "deep" costs time, not correctness.
        logger.warning(f"[TriageAgent] Classification failed, defaulting to deep: {e}")

    return "deep", "classification unavailable"


def triage_agent(state: ResearchState) -> ResearchState:
    query = state["query"]
    llm = ChatGroq(model=settings.groq_model_fast, api_key=settings.groq_api_key, temperature=0.0)

    complexity, reason = _classify(llm, query)

    if complexity not in DEPTH:
        complexity = "deep"

    depth = DEPTH[complexity]
    logger.info(f"[TriageAgent] {complexity} — {reason} (max_iterations={depth['max_iterations']})")

    patch = {
        **state,
        "complexity": complexity,
        "max_iterations": depth["max_iterations"],
        "current_step": "triage_done",
    }

    # A non-research message gets an honest direct reply rather than being
    # pushed through a pipeline that would manufacture sources for it.
    if complexity == "chat":
        try:
            response = invoke_with_retry(
                llm.with_config({"tags": [USER_VISIBLE_TAG]}),
                [SystemMessage(content=CHAT_SYSTEM_PROMPT), HumanMessage(content=query)])
            answer = clean_llm_response(str(getattr(response, "content", response)))
        except Exception as e:
            logger.warning(f"[TriageAgent] Direct reply failed: {e}")
            answer = "I'm a research assistant — ask me a question and I'll go and find sources for it."
        patch["final_report"] = answer
        patch["overall_confidence"] = 0.0
        patch["verified_claims"] = []

    return patch
