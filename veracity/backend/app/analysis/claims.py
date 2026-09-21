"""Turning speech into propositions that can be checked.

This is the step most of the product's error will live in, and it is worth being
explicit about why. People do not speak in claims. They speak in fragments,
hedges, self-corrections and asides:

    "Well, some say it's like ninety percent, maybe more, at least that's what
     I read somewhere."

There is a checkable proposition in there and several things that are not. A
system that fact-checks the sentence as written will report on a claim nobody
made; one that skips it entirely misses the substantive assertion. So extraction
does two things at once — decide what is checkable, and restate it in a
self-contained form — and keeps both the original words and the restatement, so
a bad restatement is visible rather than silent.

The other rule here is the ASR gate. A claim assembled out of words the
transcriber was unsure of is not fact-checked at all. Verifying a misheard
number produces high confidence in something that was never said, which is worse
than no verdict.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import settings
from app.db.models import ClaimVerdict
from app.llm import complete_json

log = logging.getLogger("analysis.claims")

SYSTEM = """You extract checkable factual claims from a transcript of speech.

A claim is checkable when it asserts something about the world that evidence \
could confirm or contradict: a number, a date, an event, a causal statement, an \
attribution.

These are NOT checkable, and you must not extract them:
- opinions and value judgements ("this is the best approach")
- predictions about the future ("this will double by 2030")
- statements about the speaker's own feelings or intentions
- questions, hypotheticals, and things the speaker explicitly doubts
- vague quantities with no referent ("a lot of people", "pretty big")

For each claim you extract, restate it as ONE self-contained sentence that could \
be searched for on its own. Resolve pronouns. Keep the speaker's meaning exactly \
- do not strengthen a hedge into a certainty, and do not soften an absolute \
into a maybe. If a speaker attributes a claim to someone else, keep the \
attribution in the restatement.

Return JSON:
{"claims": [{"spoken": "<the words as spoken, verbatim>",
             "proposition": "<one self-contained checkable sentence>",
             "start_ms": <integer>,
             "kind": "statistic" | "event" | "attribution" | "causal" | "other"}]}

Extract nothing rather than something weak. An empty list is a valid answer."""


@dataclass
class ExtractedClaim:
    spoken_text: str
    proposition: str
    start_ms: int
    end_ms: int
    kind: str
    asr_confidence: float
    verdict: ClaimVerdict = ClaimVerdict.unsupported

    @property
    def is_checkable(self) -> bool:
        return self.verdict != ClaimVerdict.unclear_audio


def extract(segments, *, max_claims: int = 40) -> list[ExtractedClaim]:
    """Extract claims from stored transcript segments.

    `segments` are database rows, not transcriber objects, so this runs against
    what was persisted rather than against something only the ingest path has.
    """
    if not segments:
        return []

    numbered = "\n".join(
        f"[{s.start_ms}] {s.text}" for s in segments if (s.text or "").strip()
    )
    if not numbered.strip():
        return []

    payload = complete_json(
        SYSTEM,
        f"Transcript, each line prefixed with its start time in milliseconds:\n\n"
        f"{numbered}",
        model=settings().model_smart,
    )

    raw = payload.get("claims") or payload.get("items") or []
    out: list[ExtractedClaim] = []
    for item in raw[:max_claims]:
        if not isinstance(item, dict):
            continue
        proposition = (item.get("proposition") or "").strip()
        spoken = (item.get("spoken") or proposition).strip()
        if not proposition:
            continue

        start = _as_int(item.get("start_ms"))
        seg = _segment_at(segments, start)
        # A claim the model could not place gets the timing of the segment its
        # words came from; failing that it is dropped, because a claim with no
        # timestamp cannot be cited and an uncitable verdict is not useful.
        if seg is None:
            seg = _segment_containing(segments, spoken)
        if seg is None:
            log.info("[claims] dropped an unplaceable claim: %s", proposition[:60])
            continue

        confidence = float(seg.confidence or 0.0)
        out.append(ExtractedClaim(
            spoken_text=spoken[:2000],
            proposition=proposition[:1000],
            start_ms=seg.start_ms,
            end_ms=seg.end_ms,
            kind=(item.get("kind") or "other")[:32],
            asr_confidence=round(confidence, 4),
            verdict=(ClaimVerdict.unclear_audio
                     if confidence < settings().asr_min_claim_confidence
                     else ClaimVerdict.unsupported),
        ))

    unclear = sum(1 for c in out if c.verdict == ClaimVerdict.unclear_audio)
    log.info("[claims] %d extracted, %d held back as unclear audio",
             len(out), unclear)
    return out


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _segment_at(segments, start_ms: int | None):
    """The segment covering `start_ms`, or the nearest one within a second.

    The model echoes back a timestamp we gave it, so an exact hit is the common
    case; the tolerance covers it rounding or picking the next line.
    """
    if start_ms is None:
        return None
    for s in segments:
        if s.start_ms <= start_ms <= s.end_ms:
            return s
    nearest, gap = None, None
    for s in segments:
        d = abs(s.start_ms - start_ms)
        if gap is None or d < gap:
            nearest, gap = s, d
    return nearest if gap is not None and gap <= 1000 else None


def _segment_containing(segments, spoken: str):
    needle = " ".join(spoken.lower().split())[:40]
    if len(needle) < 8:
        return None
    for s in segments:
        if needle in " ".join((s.text or "").lower().split()):
            return s
    return None
