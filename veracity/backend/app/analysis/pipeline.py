"""Running one analysis at one depth.

The three modes are a cost ladder, not three separate features: each is a
superset of the one above it and roughly four times the price. That shape is
deliberate — the expensive one is opt-in, and the interface can say what it will
cost before it runs.

    summary  one pass over the transcript                       ~1x
    deep     + structure, rhetorical moves, extracted claims    ~4x
    report   + independent verification, counter-evidence       ~15x
"""
from __future__ import annotations

import logging

from app.analysis import confidence as scoring
from app.analysis import claims as claims_mod
from app.analysis import perspectives as perspectives_mod
from app.analysis import summarise as summarise_mod
from app.analysis.search import SearchUnavailable, available as search_available
from app.db.models import AnalysisMode, ClaimVerdict

log = logging.getLogger("analysis.pipeline")


def run(segments, mode: AnalysisMode, *, asr_confidence: float | None) -> dict:
    """Produce an analysis. Returns a dict the handler persists."""
    if not segments:
        raise ValueError("there is no transcript to analyse")

    deep = mode in (AnalysisMode.deep, AnalysisMode.report)
    out = summarise_mod.summarise(segments, deep=deep)
    out["claims"] = []
    out["perspectives"] = []
    out["overall_confidence"] = None
    out["confidence_factors"] = None

    if mode == AnalysisMode.summary:
        return out

    extracted = claims_mod.extract(segments)
    log.info("[pipeline] %d claim(s) extracted", len(extracted))

    if mode == AnalysisMode.deep:
        # Claims are surfaced but not checked. Saying "we found these
        # assertions" is useful on its own, and it is honest about the fact
        # that nothing has verified them yet.
        out["claims"] = [_claim_row(i, c, None) for i, c in enumerate(extracted)]
        return out

    # ---- report: verify each claim against sources the speaker did not cite
    if not search_available():
        raise SearchUnavailable(
            "TAVILY_API_KEY is not set, so claims cannot be checked against "
            "independent sources. Deep analysis still works."
        )

    from app.analysis.verify import verify_claims
    results = verify_claims(extracted)
    out["claims"] = [_claim_row(i, c, r)
                     for i, (c, r) in enumerate(zip(extracted, results))]

    score = scoring.score_analysis(results, asr_confidence=asr_confidence)
    out["overall_confidence"] = score.value
    out["confidence_factors"] = score.as_dict()
    out["perspectives"] = perspectives_mod.for_claims(extracted)
    log.info("[pipeline] score %.2f over %s", score.value, score.counts)
    return out


def _claim_row(ordinal: int, claim, result: dict | None) -> dict:
    row = {
        "ordinal": ordinal,
        "start_ms": claim.start_ms,
        "end_ms": claim.end_ms,
        "spoken_text": claim.spoken_text,
        "proposition": claim.proposition,
        "asr_confidence": claim.asr_confidence,
        "verdict": claim.verdict,
        "verdict_confidence": None,
        "reasoning": None,
        "evidence": None,
        "independently_corroborated": False,
    }
    if result:
        row.update({
            "verdict": result.get("verdict", ClaimVerdict.unsupported),
            "verdict_confidence": result.get("verdict_confidence"),
            "reasoning": result.get("reasoning"),
            "evidence": result.get("evidence") or None,
            "independently_corroborated": bool(
                result.get("independently_corroborated")),
        })
    return row
