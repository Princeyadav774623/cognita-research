"""What the strongest disagreement with this would be.

"Give me other perspectives" asked of a model produces both-sides mush: two
paragraphs of "some argue X, others argue Y" that commit to nothing and inform
nobody. The failure is that it asks for balance instead of for evidence.

So this does something mechanical instead. For each substantive claim, it
searches specifically for material that would *contradict* it, and reports what
the strongest counter-argument actually is and who makes it. That reuses the
same search machinery as verification, pointed the other way, and it produces
something a reader can check rather than a gesture at even-handedness.

A claim with no credible counter-argument returns nothing. Manufacturing dissent
for a well-established fact is its own kind of dishonesty.
"""
from __future__ import annotations

import logging

from app.analysis.claims import ExtractedClaim
from app.analysis.search import search
from app.config import settings
from app.llm import complete_json

log = logging.getLogger("analysis.perspectives")

SYSTEM = """You are given a claim and sources found by searching for material \
that disagrees with it.

Report the strongest genuine counter-argument, if there is one.

Rules:
- If the sources contain no real disagreement, say so. Do not manufacture a \
counter-argument for a well-established fact. "None found" is the right answer \
more often than not.
- Name who holds the position, when the sources say.
- Distinguish disagreement about the fact from disagreement about what the \
fact means. Both matter; conflating them does not.
- A claim can be literally true and still misleading — omitted context, a \
cherry-picked baseline, a statistic that answers a different question. If that \
is what the sources show, say that specifically.

Return JSON:
{"has_counter": true|false,
 "summary": "<two sentences at most, or empty>",
 "held_by": "<who, or empty>",
 "kind": "disputed_fact" | "disputed_interpretation" | "missing_context" | "none"}"""


def for_claims(claims: list[ExtractedClaim], *,
               limit: int = 8) -> list[dict]:
    """Look for disagreement with the most substantive claims.

    Capped rather than exhaustive: each one is a search plus a judgement, and
    the long tail of a transcript is usually asides rather than assertions.
    """
    out: list[dict] = []
    for claim in [c for c in claims if c.is_checkable][:limit]:
        try:
            found = search(
                f"criticism OR rebuttal OR \"not true\" {claim.proposition}",
                limit=4,
            )
            if not found:
                continue
            excerpts = "\n\n".join(
                f"[{i + 1}] {e.title}\n{e.url}\n{e.snippet}"
                for i, e in enumerate(found)
            )
            payload = complete_json(
                SYSTEM,
                f"Claim: {claim.proposition}\n\nSources:\n\n{excerpts}",
                model=settings().model_smart,
            )
            if not payload.get("has_counter"):
                continue
            summary = (payload.get("summary") or "").strip()
            if not summary:
                continue
            out.append({
                "claim": claim.proposition,
                "start_ms": claim.start_ms,
                "summary": summary[:1200],
                "held_by": (payload.get("held_by") or "")[:300],
                "kind": (payload.get("kind") or "none")[:32],
                "sources": [e.as_dict() for e in found[:3]],
            })
        except Exception:                          # pragma: no cover
            log.exception("[perspectives] failed for a claim, continuing")
    return out
