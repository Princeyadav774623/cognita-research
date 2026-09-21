"""How much the whole analysis should be trusted.

Not the mean of the claim scores. A mean hides its worst member: four supported
claims and one contradicted one score the same as five mediocre ones, and the
contradicted claim is the single most important thing on the page.

Instead the score is capped by the quality of what it rests on. Caps rather than
penalties, because a penalty is a subtraction that enough good claims can win
back — and no number of supported claims makes a transcript the model could
barely hear into a reliable one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.db.models import ClaimVerdict

CONTRADICTED_WEIGHT = 2.0      # cannot be averaged away by its neighbours
UNSUPPORTED_WEIGHT = 1.3

CAP_POOR_AUDIO = 0.50          # the transcript itself is in doubt
CAP_MOSTLY_UNCHECKED = 0.60    # too little was checkable to conclude much
CAP_ANY_CONTRADICTED = 0.70    # something in here is wrong
CAP_FEW_CLAIMS = 0.75          # too thin a basis for a high score

POOR_AUDIO_BELOW = 0.70
MIN_CLAIMS_FOR_HIGH = 5


@dataclass
class Score:
    value: float
    factors: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"score": self.value, "factors": self.factors,
                "counts": self.counts}


def score_analysis(results: list[dict], *,
                   asr_confidence: float | None) -> Score:
    counts = {v.value: 0 for v in ClaimVerdict}
    for r in results:
        verdict = r.get("verdict")
        key = verdict.value if hasattr(verdict, "value") else str(verdict)
        counts[key] = counts.get(key, 0) + 1

    checked = [r for r in results
               if _key(r) in ("supported", "contradicted", "unsupported")]
    factors: list[str] = []

    if not checked:
        factors.append(
            "Nothing was checkable: the analysis found no factual claims, or "
            "none clear enough in the audio to check."
        )
        return Score(0.0, factors, counts)

    weighted_total = 0.0
    weight_sum = 0.0
    for r in checked:
        key = _key(r)
        confidence = float(r.get("verdict_confidence") or 0.0)
        if key == "supported":
            value, weight = confidence, 1.0
        elif key == "contradicted":
            value, weight = 0.0, CONTRADICTED_WEIGHT
        else:
            value, weight = 0.35, UNSUPPORTED_WEIGHT
        weighted_total += value * weight
        weight_sum += weight

    value = weighted_total / weight_sum if weight_sum else 0.0

    caps: list[tuple[float, str]] = []
    if asr_confidence is not None and asr_confidence < POOR_AUDIO_BELOW:
        caps.append((CAP_POOR_AUDIO,
                     f"The transcription was only {asr_confidence:.0%} "
                     f"confident, so the claims themselves may be misheard."))
    unclear = counts.get("unclear_audio", 0)
    if unclear and unclear >= len(results) / 2:
        caps.append((CAP_MOSTLY_UNCHECKED,
                     f"{unclear} of {len(results)} claims were too unclear in "
                     f"the audio to check."))
    if counts.get("contradicted", 0):
        caps.append((CAP_ANY_CONTRADICTED,
                     f"{counts['contradicted']} claim(s) are contradicted by "
                     f"independent sources."))
    if len(checked) < MIN_CLAIMS_FOR_HIGH:
        caps.append((CAP_FEW_CLAIMS,
                     f"Only {len(checked)} claim(s) could be checked, which is "
                     f"a thin basis for a high score."))

    for cap, why in caps:
        if value > cap:
            value = cap
        factors.append(why)

    if counts.get("supported", 0) and not factors:
        factors.append(
            f"{counts['supported']} claim(s) supported by sources the speaker "
            f"did not cite."
        )
    return Score(round(value, 4), factors, counts)


def _key(r: dict) -> str:
    v = r.get("verdict")
    return v.value if hasattr(v, "value") else str(v)
