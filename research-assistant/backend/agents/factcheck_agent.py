"""Fact-check agent — decides whether the draft's claims are actually supported.

Two things were structurally wrong with the previous version, and both made the
confidence score mean something other than what the interface says it means.

First, it verified every claim against the same documents the analyst wrote the
draft from. A claim faithfully summarised from a source always verifies against
that source, including when the source is wrong — so the number measured
summarisation fidelity, not support. Claims are now also checked against
evidence retrieved independently, and a claim corroborated by a source the
draft was not written from is marked as such.

Second, evidence was assembled positionally: the first 1,000 characters of each
document, cut to 6,000 characters overall. On a 40-source run that is about the
top of the first six, so claims drawn from anywhere else were unverifiable in
principle and came back "unverified" for reasons unrelated to their truth.
Evidence is now selected per claim by relevance across every source (see
agents/evidence.py).

Batching is preserved. All claims still go out in a single LLM call, because
verifying them one at a time is what previously made this node dominate the
pipeline — a measured 257s of a 361s run. Each claim now carries its own
evidence block inside that one call.
"""

import asyncio
import json
import logging
import re
from typing import List, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field
from tavily import TavilyClient

from agents.evidence import select_evidence
from confidence import score_run
from config import get_settings
from graph.state import ResearchState, VerifiedClaim
from utils import invoke_with_retry, clean_llm_response, normalize_url, sanitize_external_text

logger = logging.getLogger(__name__)
settings = get_settings()

# Passages of prior evidence per claim, and corroborating results fetched fresh.
EVIDENCE_PER_CLAIM = 4
CORROBORATION_RESULTS = 3
# Claims are verified in one call; this bounds how much of that call one claim
# can occupy so a single verbose source can't crowd the others out.
MAX_EVIDENCE_CHARS_PER_CLAIM = 2600


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

BATCH_VERIFY_PROMPT = """You are a rigorous fact-checker judging several claims at once.

Each claim below is followed by its own evidence block. Judge each claim ONLY
against the evidence printed under it, and judge each one independently.

Evidence is labelled by where it came from:
- [PRIOR] passages from the documents the draft was written from.
- [INDEPENDENT] passages retrieved separately, afterwards, to check the claim.

Scoring:
- Support from an [INDEPENDENT] source is stronger evidence than support from a
  [PRIOR] one, because a claim always agrees with the text it was summarised
  from. Two independent sources agreeing warrants high confidence.
- If only [PRIOR] evidence supports the claim, cap confidence at 0.7.
- If the evidence does not state the fact, set verified=false and confidence
  near 0.0. Do not reason from your own knowledge — absence of evidence here
  means unverified, not false.

Cite the title or URL of whichever passage actually settled it."""


async def factcheck_agent(state: ResearchState) -> ResearchState:
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

    claims = await asyncio.to_thread(extract_claims, llm, state["draft_answer"])
    logger.info(f"[FactCheckAgent] Extracted {len(claims)} claims to verify")

    # Claims already settled on an earlier reflective pass don't need
    # re-verifying against evidence that only grew.
    previous = {c["claim"]: c for c in state.get("verified_claims", [])}
    pending = [c for c in claims if c not in previous]
    carried = [previous[c] for c in claims if c in previous]
    if carried:
        logger.info(f"[FactCheckAgent] Reusing {len(carried)} verdict(s) from a previous pass")

    verified_claims = carried
    if pending:
        prior_docs = state.get("source_documents", [])
        corroboration = await _gather_corroboration(pending)
        blocks = [
            _evidence_block(claim, prior_docs, corroboration.get(claim, []))
            for claim in pending
        ]
        fresh = await asyncio.to_thread(verify_claims_batch, llm, pending, blocks)
        verified_claims = carried + fresh

    for result in verified_claims:
        status = "✓" if result["verified"] else "✗"
        independent = " [independent]" if result.get("independently_corroborated") else ""
        logger.info(
            f"[FactCheckAgent] {status} ({result['confidence']:.0%}){independent} "
            f"{result['claim'][:60]}..."
        )

    # The run's score is not the mean of the claim scores: it is capped by how
    # much evidence sits underneath them. See confidence.py for why.
    assessment = score_run(verified_claims, state.get("source_documents", []))

    corroborated = sum(1 for c in verified_claims if c.get("independently_corroborated"))
    logger.info(
        f"[FactCheckAgent] Overall confidence: {assessment['score']:.2f} "
        f"({corroborated}/{len(verified_claims)} independently corroborated)"
    )
    for note in assessment["to_improve"]:
        logger.info(f"[FactCheckAgent] Limiting factor: {note}")

    return {
        **state,
        "verified_claims": verified_claims,
        "overall_confidence": assessment["score"],
        "confidence_factors": assessment["factors"],
        "confidence_to_improve": assessment["to_improve"],
        "current_step": "factcheck_done",
    }


# =============================================
# Independent corroboration
# =============================================

async def _gather_corroboration(claims: list[str]) -> dict[str, list[dict]]:
    """Search for each claim on its own, concurrently.

    This is the part that makes the verdict mean something: it looks for
    sources the analyst did not already use. Failure is tolerated — a claim
    with no corroborating search still gets judged on prior evidence, just
    without the confidence that independent agreement would earn it.
    """
    if not settings.tavily_api_key or not claims:
        return {}

    results = await asyncio.gather(
        *(asyncio.to_thread(_search_one_claim, claim) for claim in claims),
        return_exceptions=True,
    )

    corroboration: dict[str, list[dict]] = {}
    for claim, result in zip(claims, results):
        if isinstance(result, Exception):
            logger.warning(f"[FactCheckAgent] Corroboration search failed for '{claim[:50]}': {result}")
            continue
        corroboration[claim] = result

    found = sum(1 for v in corroboration.values() if v)
    logger.info(f"[FactCheckAgent] Corroborating evidence found for {found}/{len(claims)} claim(s)")
    return corroboration


def _search_one_claim(claim: str) -> list[dict]:
    tavily = TavilyClient(api_key=settings.tavily_api_key)
    response = tavily.search(
        query=claim,
        search_depth="basic",     # snippets are enough to corroborate a single fact
        max_results=CORROBORATION_RESULTS,
        include_answer=False,
        include_raw_content=False,
    )
    return [
        {
            "title": r.get("title", "Untitled"),
            "url": normalize_url(r.get("url", "")),
            "text": sanitize_external_text(r.get("content", "")),
            "origin": "independent",
        }
        for r in response.get("results", [])
        if r.get("content")
    ]


# =============================================
# Evidence assembly
# =============================================

def _evidence_block(claim: str, prior_docs: list[dict], corroborating: list[dict]) -> dict:
    """Build one claim's evidence: the most relevant passages from the documents
    the draft used, plus anything retrieved independently for this claim."""
    prior = select_evidence(claim, prior_docs, top_k=EVIDENCE_PER_CLAIM)

    # Independently-found sources the draft already used aren't independent.
    prior_urls = {normalize_url(d.get("url", "")) for d in prior_docs}
    independent = [
        d for d in corroborating
        if d.get("url") and normalize_url(d["url"]) not in prior_urls
    ]
    independent_passages = select_evidence(claim, independent, top_k=CORROBORATION_RESULTS)

    lines, used = [], 0
    for tag, passages in (("INDEPENDENT", independent_passages), ("PRIOR", prior)):
        for p in passages:
            entry = f"[{tag}] {p['title']} ({p['url']})\n{p['text']}"
            if used + len(entry) > MAX_EVIDENCE_CHARS_PER_CLAIM:
                continue
            lines.append(entry)
            used += len(entry)

    return {
        "text": "\n\n".join(lines) if lines else "No evidence retrieved for this claim.",
        "has_independent": bool(independent_passages),
    }


# =============================================
# Verification
# =============================================

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


def verify_claims_batch(llm: ChatGroq, claims: list[str], blocks: list[dict]) -> list[VerifiedClaim]:
    """Verify every claim in a single call, each against its own evidence.

    Falls back to the per-claim path only if the batched call fails outright,
    so a malformed batch response degrades into slower-but-correct rather than
    losing verdicts entirely.
    """
    if not claims:
        return []

    sections = []
    for i, (claim, block) in enumerate(zip(claims, blocks)):
        sections.append(f"### Claim {i}\n{claim}\n\nEvidence for claim {i}:\n{block['text']}")
    human_content = "\n\n".join(sections)

    system = (
        BATCH_VERIFY_PROMPT
        + f"\n\nReturn one verdict per claim, {len(claims)} in total, each carrying its claim_index."
    )

    def _assemble(raw_verdicts) -> list[VerifiedClaim]:
        by_index = {}
        for v in raw_verdicts:
            idx = int(v.get("claim_index", -1)) if isinstance(v, dict) else int(v.claim_index)
            if 0 <= idx < len(claims):
                by_index[idx] = v
        out = []
        for i, claim in enumerate(claims):
            has_independent = blocks[i].get("has_independent", False) if i < len(blocks) else False
            v = by_index.get(i)
            if v is None:
                out.append({"claim": claim, "verified": False, "confidence": 0.5,
                            "source": "Not returned by verifier",
                            "independently_corroborated": False})
                continue
            get = (lambda k, d: v.get(k, d)) if isinstance(v, dict) else (lambda k, d: getattr(v, k, d))
            verified = bool(get("verified", False))
            out.append({
                "claim": claim,
                "verified": verified,
                "confidence": float(get("confidence", 0.5)),
                "source": str(get("source", "Unknown")),
                # Only a claim that both held up and had independent evidence
                # in front of the verifier counts as corroborated.
                "independently_corroborated": verified and has_independent,
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

    return [
        {**verify_claim(llm, c, blocks[i]["text"] if i < len(blocks) else ""),
         "independently_corroborated": False}
        for i, c in enumerate(claims)
    ]


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
