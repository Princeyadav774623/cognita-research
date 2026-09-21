"""Checking a claim against evidence the speaker never cited.

The naive version of this is circular and worth naming, because it looks
identical from the outside: extract claims from the transcript, then check them
against the transcript. A claim faithfully drawn from what someone said always
agrees with what they said — including when they were wrong. Such a system
measures transcription fidelity while its interface calls the result
verification.

So every claim is searched for separately, and the verdict is formed only from
what that search returned. The speaker's own words are context for reading the
evidence, never evidence themselves.
"""
from __future__ import annotations

import concurrent.futures
import logging

from app.analysis.claims import ExtractedClaim
from app.analysis.search import Evidence, SearchUnavailable, search
from app.config import settings
from app.db.models import ClaimVerdict
from app.llm import complete_json

log = logging.getLogger("analysis.verify")

SYSTEM = """You judge whether independent evidence supports a claim someone made.

You are given one claim and excerpts from sources found by searching for that \
claim. The sources were NOT chosen by the speaker.

Decide one of:
- "supported"     the evidence states or clearly implies the claim
- "contradicted"  the evidence states something incompatible with it
- "unsupported"   the evidence does not settle it either way
- "not_checkable" this is an opinion, prediction or value judgement after all

Rules you must follow:
- Judge the claim as stated. If it says "over 2,300 km" and the evidence says \
"2,300 km", that is supported. If it says "over 3,000 km", that is contradicted.
- A source that merely discusses the topic is not support. It has to bear on \
the specific assertion.
- Do not use your own knowledge as evidence. If the excerpts do not settle it, \
the answer is "unsupported", however confident you personally feel.
- Quote the exact sentence you relied on. If you cannot quote one, you do not \
have evidence.

Return JSON:
{"verdict": "...",
 "confidence": <0.0-1.0>,
 "reasoning": "<two sentences at most>",
 "quote": "<the sentence you relied on, or empty>",
 "source_url": "<the url it came from, or empty>"}"""


def verify_claims(claims: list[ExtractedClaim], *,
                  max_workers: int = 4) -> list[dict]:
    """Verify each checkable claim. Returns one result dict per claim."""
    checkable = [c for c in claims if c.is_checkable]
    if not checkable:
        return [_skipped(c) for c in claims]

    results: dict[int, dict] = {}
    # Concurrent because each claim is an independent search plus an
    # independent judgement, and doing forty of them in series is minutes of
    # waiting for no benefit.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_verify_one, c): i
                   for i, c in enumerate(claims) if c.is_checkable}
        for future in concurrent.futures.as_completed(futures):
            i = futures[future]
            try:
                results[i] = future.result()
            except SearchUnavailable:
                raise
            except Exception as exc:               # pragma: no cover
                log.exception("[verify] claim %d failed", i)
                results[i] = _errored(claims[i], exc)

    return [results.get(i) or _skipped(c) for i, c in enumerate(claims)]


def _verify_one(claim: ExtractedClaim) -> dict:
    evidence = search(claim.proposition, limit=5)
    if not evidence:
        return {
            "verdict": ClaimVerdict.unsupported,
            "verdict_confidence": 0.0,
            "reasoning": "No sources were found for this claim.",
            "evidence": [],
            "independently_corroborated": False,
        }

    excerpts = "\n\n".join(
        f"[{i + 1}] {e.title}\n{e.url}\n{e.snippet}"
        for i, e in enumerate(evidence)
    )
    payload = complete_json(
        SYSTEM,
        f"Claim: {claim.proposition}\n\n"
        f"As spoken: \"{claim.spoken_text}\"\n\n"
        f"Independent sources:\n\n{excerpts}",
        model=settings().model_smart,
    )

    verdict = _verdict(payload.get("verdict"))
    quote = (payload.get("quote") or "").strip()
    confidence = _clamp(payload.get("confidence"))

    # A verdict with no quotable sentence behind it is an opinion about the
    # claim, not a finding about the evidence, and it is capped accordingly.
    if verdict in (ClaimVerdict.supported, ClaimVerdict.contradicted) and not quote:
        confidence = min(confidence, 0.5)

    return {
        "verdict": verdict,
        "verdict_confidence": confidence,
        "reasoning": (payload.get("reasoning") or "")[:2000],
        "evidence": [e.as_dict() for e in evidence],
        "quote": quote[:1000],
        "source_url": (payload.get("source_url") or "")[:2000],
        # Every source here came from a search for this claim, so a supported
        # verdict is corroborated by construction. The flag exists so the
        # distinction survives if a future path ever reuses prior sources.
        "independently_corroborated": verdict == ClaimVerdict.supported,
    }


def _skipped(claim: ExtractedClaim) -> dict:
    return {
        "verdict": claim.verdict,
        "verdict_confidence": None,
        "reasoning": (
            "Not checked: the transcriber was not confident enough about these "
            "words. Verifying a misheard sentence would report confidence in "
            "something that was never said."
            if claim.verdict == ClaimVerdict.unclear_audio else ""
        ),
        "evidence": [],
        "independently_corroborated": False,
    }


def _errored(claim: ExtractedClaim, exc: Exception) -> dict:
    return {
        "verdict": ClaimVerdict.unsupported,
        "verdict_confidence": 0.0,
        "reasoning": f"Could not check this claim: {type(exc).__name__}.",
        "evidence": [],
        "independently_corroborated": False,
    }


def _verdict(value) -> ClaimVerdict:
    try:
        return ClaimVerdict((value or "").strip().lower())
    except ValueError:
        return ClaimVerdict.unsupported


def _clamp(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
