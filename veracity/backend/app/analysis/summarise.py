"""Summary and structure — the two cheaper depths."""
from __future__ import annotations

import logging

from app.config import settings
from app.llm import complete_json

log = logging.getLogger("analysis.summarise")

SUMMARY_SYSTEM = """You summarise a transcript of speech.

Write for someone deciding whether to watch it. Say what was actually discussed, \
in the speaker's own terms, without editorialising about whether they were right.

Every key point must carry the timestamp it was made at, taken from the line \
prefixes in the transcript.

Return JSON:
{"summary": "<two or three sentences of prose>",
 "key_points": [{"point": "<one sentence>", "start_ms": <integer>}]}"""

DEEP_SYSTEM = """You analyse the structure of a transcript of speech.

Beyond what was said, identify how it was argued: what the segments are, what \
each is doing, and what the speaker is ultimately asking the listener to accept.

Be specific about rhetorical moves where they matter — an anecdote standing in \
for evidence, a statistic with no baseline, an appeal to an unnamed authority. \
Do not invent them; if the speaking is straightforward, say so.

Return JSON:
{"summary": "<a paragraph>",
 "key_points": [{"point": "<one sentence>", "start_ms": <integer>}],
 "topics": [{"title": "<short>", "start_ms": <integer>, "end_ms": <integer>,
             "doing": "<what this stretch is doing in the argument>"}],
 "thesis": "<what the listener is being asked to accept, in one sentence>"}"""


def summarise(segments, *, deep: bool = False) -> dict:
    numbered = "\n".join(
        f"[{s.start_ms}] {s.text}" for s in segments if (s.text or "").strip()
    )
    if not numbered.strip():
        return {"summary": "", "key_points": [], "topics": []}

    payload = complete_json(
        DEEP_SYSTEM if deep else SUMMARY_SYSTEM,
        f"Transcript, each line prefixed with its start time in milliseconds:\n\n"
        f"{numbered}",
        model=settings().model_smart if deep else settings().model_fast,
        temperature=0.2,
        max_tokens=3000,
    )
    return {
        "summary": (payload.get("summary") or "").strip(),
        "key_points": _points(payload.get("key_points")),
        "topics": _topics(payload.get("topics")),
        "thesis": (payload.get("thesis") or "").strip() or None,
    }


def _points(raw) -> list[dict]:
    out = []
    for p in (raw or [])[:20]:
        if isinstance(p, dict) and (p.get("point") or "").strip():
            out.append({"point": p["point"].strip()[:500],
                        "start_ms": _int(p.get("start_ms"))})
        elif isinstance(p, str) and p.strip():
            out.append({"point": p.strip()[:500], "start_ms": None})
    return out


def _topics(raw) -> list[dict]:
    out = []
    for t in (raw or [])[:15]:
        if not isinstance(t, dict) or not (t.get("title") or "").strip():
            continue
        out.append({
            "title": t["title"].strip()[:200],
            "start_ms": _int(t.get("start_ms")),
            "end_ms": _int(t.get("end_ms")),
            "doing": (t.get("doing") or "").strip()[:400] or None,
        })
    return out


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
