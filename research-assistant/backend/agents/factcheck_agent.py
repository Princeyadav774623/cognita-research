from pydantic import BaseModel, Field
from typing import List, Optional
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from config import get_settings
from graph.state import ResearchState, VerifiedClaim
from utils import invoke_with_retry
import json
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


# =============================================
# FACT-CHECK AGENT (Pydantic Structured Output)
# Extracts key claims and verifies each against sources
# =============================================

class ClaimsList(BaseModel):
    claims: List[str] = Field(
        description="Key factual claims from the research draft to be verified.",
        default_factory=list
    )


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

    # Step 2: Verify each claim against sources
    context = build_source_context(state.get("source_documents", []))
    verified_claims = []

    for claim in claims:
        result = verify_claim(llm, claim, context)
        verified_claims.append(result)
        status = "✓" if result["verified"] else "✗"
        logger.info(f"[FactCheckAgent] {status} ({result['confidence']:.0%}) {claim[:60]}...")

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
        if isinstance(result, ClaimsList):
            return result.claims
        elif isinstance(result, dict) and "claims" in result:
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
        raw = response.content.strip()
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
        raw = response.content.strip()
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

