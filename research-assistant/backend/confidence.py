"""How a run's confidence score is calculated, and why.

The old score was the mean of the per-claim confidences. That is the wrong
shape for the question it is answering, in four ways:

1. A mean hides its worst member. Four solid claims and one fabrication scored
   the same as five middling ones, and the fabrication is the thing a research
   tool must not bury.
2. It ignored how much evidence was behind the answer. Two sources and twenty
   produced identical numbers.
3. It ignored whether the text was ever actually read. A source blocked by a
   paywall degrades to the search engine's two-sentence snippet, which is far
   weaker evidence than the paper it stands in for, and nothing reflected that.
4. It ignored corroboration. A claim confirmed by a source the draft was not
   written from is worth far more than one that merely agrees with its own
   summary — that distinction is the entire point of the fact-checking pass.

So the score starts from the claims and is then *capped* by the quality of the
evidence underneath them. Caps rather than subtractions, because thin evidence
does not make an answer wrong — it makes a high score unjustifiable.

Every adjustment is reported alongside the number. A score a reader cannot
interrogate is just a decoration, and `to_improve` says what would actually
raise it, which is the only actionable part.
"""

from graph.state import SourceDocument, VerifiedClaim

# Distinct sources below which a confident answer isn't justifiable, whatever
# the individual claims say.
MIN_SOURCES_FOR_HIGH = 5
MIN_SOURCES_FOR_MODERATE = 3

CAP_THIN_EVIDENCE = 0.60
CAP_MODERATE_EVIDENCE = 0.80
CAP_MOSTLY_SNIPPETS = 0.70

# An unverified claim drags the score down by more than its share of the mean.
UNVERIFIED_WEIGHT = 1.5
# Full independent corroboration is worth this much on top.
CORROBORATION_BONUS = 0.10


def score_run(claims: list[VerifiedClaim], documents: list[SourceDocument]) -> dict:
    """Return the run's confidence plus the reasoning behind it."""
    factors: list[dict] = []
    to_improve: list[str] = []

    if not claims:
        return {
            "score": 0.0,
            "factors": [{"label": "No claims verified",
                         "detail": "Nothing was extracted from the draft to check."}],
            "to_improve": ["Ask a more specific question so there are factual claims to verify."],
        }

    verified = [c for c in claims if c.get("verified")]
    unverified = [c for c in claims if not c.get("verified")]

    # Weighted mean: an unverified claim counts for more than its share, so one
    # unsupported statement can't hide behind four good ones.
    numerator = sum(c.get("confidence", 0.0) for c in verified)
    numerator += sum(c.get("confidence", 0.0) * UNVERIFIED_WEIGHT for c in unverified)
    denominator = len(verified) + len(unverified) * UNVERIFIED_WEIGHT
    score = numerator / denominator if denominator else 0.0

    factors.append({
        "label": f"{len(verified)} of {len(claims)} claims supported",
        "detail": "Unsupported claims are weighted more heavily than supported ones.",
    })
    if unverified:
        to_improve.append(
            f"{len(unverified)} claim(s) had no supporting evidence in the sources found."
        )

    # Corroboration: agreeing with a source the draft was not written from.
    corroborated = [c for c in verified if c.get("independently_corroborated")]
    if verified:
        ratio = len(corroborated) / len(verified)
        bonus = CORROBORATION_BONUS * ratio
        score = min(1.0, score + bonus)
        factors.append({
            "label": f"{len(corroborated)} of {len(verified)} independently corroborated",
            "detail": "Confirmed against a source the draft was not written from.",
        })
        if ratio < 0.5:
            to_improve.append(
                "Few claims were confirmed by an independent source — agreement with the "
                "documents the answer was written from is weaker evidence."
            )

    # Evidence breadth.
    distinct = len({d.get("url", "") for d in documents if d.get("url")})
    if distinct < MIN_SOURCES_FOR_MODERATE:
        score = min(score, CAP_THIN_EVIDENCE)
        factors.append({"label": f"Only {distinct} source(s) available",
                        "detail": f"Score capped at {CAP_THIN_EVIDENCE:.0%} on thin evidence."})
        to_improve.append("Broaden the question, or allow another research pass to gather more sources.")
    elif distinct < MIN_SOURCES_FOR_HIGH:
        score = min(score, CAP_MODERATE_EVIDENCE)
        factors.append({"label": f"{distinct} sources",
                        "detail": f"Score capped at {CAP_MODERATE_EVIDENCE:.0%} below {MIN_SOURCES_FOR_HIGH} sources."})
    else:
        factors.append({"label": f"{distinct} sources", "detail": "Enough breadth for a confident answer."})

    # Extraction quality: a snippet is not the paper it stands for.
    tracked = [d for d in documents if d.get("via_fallback") is not None]
    if tracked:
        snippets = sum(1 for d in tracked if d.get("via_fallback"))
        if snippets > len(tracked) / 2:
            score = min(score, CAP_MOSTLY_SNIPPETS)
            factors.append({
                "label": f"{snippets} of {len(tracked)} sources were search snippets only",
                "detail": f"Full text could not be extracted; capped at {CAP_MOSTLY_SNIPPETS:.0%}.",
            })
            to_improve.append(
                "Most sources could not be read in full (paywalls or blocked pages). "
                "Sources with open full text would raise this."
            )

    return {
        "score": round(max(0.0, min(1.0, score)), 2),
        "factors": factors,
        "to_improve": to_improve,
    }
