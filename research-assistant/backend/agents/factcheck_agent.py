from pydantic import BaseModel, Field
from typing import List, Optional
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from config import get_settings
from graph.state import ResearchState, VerifiedClaim
from utils import invoke_with_retry, clean_llm_response
import json
import re
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


class ClaimsList(BaseModel):
    claims: List[str] = Field(
        description="Key factual claims from the research draft to be verified.",
        default_factory=list
    )


class BatchedVerdict(BaseModel):
    """One claim's verdict inside a batched verification response."""
    claim_index: int = Field(description="0-based index of the claim being judged.")
    verified: bool = Field(default=False)
    confidence: float = Field(default=0.5, description="0.0-1.0.")
    source: str = Field(default="Not found in sources")


class BatchedVerification(BaseModel):
    verdicts: List[BatchedVerdict] = Field(default_factory=list)


class ClaimVerification(BaseModel):
    verified: bool = Field(description="Whether the claim is supported by the source text.")
    confidence: float = Field(default=0.5, description="Confidence score between 0.0 and 1.0.")
    source: str = Field(default="Not found in sources", description="Title or URL of the supporting source.")
    explanation: Optional[str] = Field(default="", description="Brief justification.")


EXTRACT_CLAIMS_PROMPT = """Extract the 5 most important factual claims from the following research answer.
Focus on empirical claims, statistics, dates, names, and core findings.
"""

VERIFY_CLAIM_PROMPT = """You are a rigorous fact-checker. Given a claim and source documents, determine if the claim is directly supported.
Be objective and strict: if the sources do not mention the fact, mark verified=False and confidence=0.0.
"""


def factcheck_agent(state: ResearchState) -> ResearchState:
    logger.info("[FactCheckAgent] Starting fact verification")

    if not state.get("draft_answer"):
        return {
            **state,
            "verified_claims": [],
            "overall_confidence": 0.0,
            "current_step": "factcheck_done",
        }

    llm = ChatGroq(
        model=settings.groq_model_smart,
        api_key=settings.groq_api_key,
        temperature=0.0,    # deterministic verification
    )

    # Step 1: Extract key claims from the draft
    claims = extract_claims(llm, state["draft_answer"])
    logger.info(f"[FactCheckAgent] Extracted {len(claims)} claims to verify")

    # Step 2: Verify the claims against sources.
    #
    # All claims go in ONE call. Verifying them one at a time re-sent the same
    # ~1k-token evidence block once per claim, which on a tokens-per-minute
    # limited account is what actually made this node dominate the pipeline
    # (measured: 257s of a 361s run). Parallelising the old loop makes it
    # worse, not better — concurrent calls hit the rate limit harder and
    # spend the extra time in backoff.
    context = build_source_context(state.get("source_documents", []))

    # Claims already settled on an earlier reflective pass don't need
    # re-verifying against evidence that only grew.
    previous = {c["claim"]: c for c in state.get("verified_claims", [])}
    pending = [c for c in claims if c not in previous]
    carried = [previous[c] for c in claims if c in previous]
    if carried:
        logger.info(f"[FactCheckAgent] Reusing {len(carried)} verdict(s) from a previous pass")

    verified_claims = carried + (verify_claims_batch(llm, pending, context) if pending else [])

    for result in verified_claims:
        status = "✓" if result["verified"] else "✗"
        logger.info(f"[FactCheckAgent] {status} ({result['confidence']:.0%}) {result['claim'][:60]}...")

    # Step 3: Calculate overall confidence
    if verified_claims:
        overall_confidence = sum(c["confidence"] for c in verified_claims) / len(verified_claims)
    else:
        overall_confidence = 0.5

    logger.info(f"[FactCheckAgent] Overall confidence: {overall_confidence:.2f}")

    return {
        **state,
        "verified_claims": verified_claims,
        "overall_confidence": round(overall_confidence, 2),
        "current_step": "factcheck_done",
    }


def extract_claims(llm: ChatGroq, draft: str) -> list[str]:
    """Extract key factual claims using structured output with fallback."""
    try:
        structured_llm = llm.with_structured_output(ClaimsList)
        messages = [
            SystemMessage(content=EXTRACT_CLAIMS_PROMPT),
            HumanMessage(content=draft),
        ]
        result = invoke_with_retry(structured_llm, messages)
        if isinstance(result, ClaimsList) and result.claims:
            return result.claims
        elif isinstance(result, dict) and result.get("claims"):
            return result["claims"]
        elif isinstance(result, list):
            return result
    except Exception as e:
        logger.debug(f"[FactCheckAgent] Structured output extraction fallback: {e}")

    # Fallback to standard prompt extraction
    try:
        fallback_prompt = """Extract the 5 most important factual claims from the following research answer.
Return ONLY a JSON array of strings: ["Claim 1", "Claim 2"]"""
        messages = [
            SystemMessage(content=fallback_prompt),
            HumanMessage(content=draft),
        ]
        response = invoke_with_retry(llm, messages)
        raw = clean_llm_response(str(getattr(response, "content", response)))
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict) and "claims" in parsed:
            return parsed["claims"]
    except Exception as e:
        logger.warning(f"[FactCheckAgent] Could not extract claims: {e}")

    return []


def verify_claims_batch(llm: ChatGroq, claims: list[str], context: str) -> list[VerifiedClaim]:
    """Verify every claim in a single call, sending the evidence once.

    Falls back to the per-claim path only if the batched call fails outright,
    so a malformed batch response degrades into slower-but-correct rather than
    losing verdicts entirely.
    """
    if not claims:
        return []

    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(claims))
    human_content = (
        f"Source documents:\n{context[:6000]}\n\n"
        f"Claims to verify (judge each independently, by index):\n{numbered}"
    )
    system = (
        VERIFY_CLAIM_PROMPT
        + f"\nReturn one verdict per claim, {len(claims)} in total, each carrying its claim_index."
    )

    def _assemble(raw_verdicts) -> list[VerifiedClaim]:
        by_index = {}
        for v in raw_verdicts:
            idx = int(v.get("claim_index", -1)) if isinstance(v, dict) else int(v.claim_index)
            if 0 <= idx < len(claims):
                by_index[idx] = v
        out = []
        for i, claim in enumerate(claims):
            v = by_index.get(i)
            if v is None:
                out.append({"claim": claim, "verified": False, "confidence": 0.5,
                            "source": "Not returned by verifier"})
                continue
            get = (lambda k, d: v.get(k, d)) if isinstance(v, dict) else (lambda k, d: getattr(v, k, d))
            out.append({
                "claim": claim,
                "verified": bool(get("verified", False)),
                "confidence": float(get("confidence", 0.5)),
                "source": str(get("source", "Unknown")),
            })
        return out

    try:
        structured_llm = llm.with_structured_output(BatchedVerification)
        result = invoke_with_retry(structured_llm, [
            SystemMessage(content=system), HumanMessage(content=human_content)])
        if isinstance(result, BatchedVerification) and result.verdicts:
            return _assemble(result.verdicts)
        if isinstance(result, dict) and result.get("verdicts"):
            return _assemble(result["verdicts"])
    except Exception as e:
        logger.debug(f"[FactCheckAgent] Batched structured output fallback: {e}")

    try:
        json_system = system + (
            '\nRespond with JSON only: {"verdicts": [{"claim_index": 0, "verified": true, '
            '"confidence": 0.0-1.0, "source": "..."}]}'
        )
        response = invoke_with_retry(llm, [
            SystemMessage(content=json_system), HumanMessage(content=human_content)])
        raw = clean_llm_response(str(getattr(response, "content", response)))
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            if data.get("verdicts"):
                return _assemble(data["verdicts"])
    except Exception as e:
        logger.warning(f"[FactCheckAgent] Batched verification failed, falling back per-claim: {e}")

    return [verify_claim(llm, c, context) for c in claims]


def verify_claim(llm: ChatGroq, claim: str, context: str) -> VerifiedClaim:
    """Verify a single claim against source documents using structured output."""
    human_content = f"Claim to verify: \"{claim}\"\n\nSource documents:\n{context[:4000]}"

    try:
        structured_llm = llm.with_structured_output(ClaimVerification)
        messages = [
            SystemMessage(content=VERIFY_CLAIM_PROMPT),
            HumanMessage(content=human_content),
        ]
        result = invoke_with_retry(structured_llm, messages)
        if isinstance(result, ClaimVerification):
            return {
                "claim": claim,
                "verified": result.verified,
                "confidence": float(result.confidence),
                "source": result.source or "Unknown",
            }
        elif isinstance(result, dict):
            return {
                "claim": claim,
                "verified": bool(result.get("verified", False)),
                "confidence": float(result.get("confidence", 0.5)),
                "source": str(result.get("source", "Unknown")),
            }
    except Exception as e:
        logger.debug(f"[FactCheckAgent] Structured output verification fallback: {e}")

    # Fallback to JSON parsing
    try:
        messages = [
            SystemMessage(content=f"{VERIFY_CLAIM_PROMPT}\nRespond with JSON: {{\"verified\": true/false, \"confidence\": 0.0-1.0, \"source\": \"...\"}}"),
            HumanMessage(content=human_content),
        ]
        response = invoke_with_retry(llm, messages)
        raw = clean_llm_response(str(getattr(response, "content", response)))
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        return {
            "claim": claim,
            "verified": bool(data.get("verified", False)),
            "confidence": float(data.get("confidence", 0.5)),
            "source": str(data.get("source", "Unknown")),
        }
    except Exception as e:
        logger.warning(f"[FactCheckAgent] Verification exception: {e}")
        return {
            "claim": claim,
            "verified": False,
            "confidence": 0.5,
            "source": "Verification failed",
        }


def build_source_context(documents: list) -> str:
    parts = []
    for doc in documents:
        parts.append(f"[{doc['title']}] ({doc['url']})\n{doc['text'][:1000]}")
    return "\n\n".join(parts)

