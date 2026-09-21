"""Group timed segments into retrieval units that keep their timing.

Chunking a transcript is not chunking a document. A document chunk needs only to
be findable; a transcript chunk also has to be *locatable* — the whole point of
retrieving it is to send the reader to the moment it came from. So every chunk
carries the span it covers, and a chunk that is built by splitting one long
utterance gets the timing of the words it actually kept, not of the utterance it
came from.

Two rules follow from that:

  - Prefer not to split an utterance. Speech has natural boundaries and they are
    better than any character count.
  - When an utterance must be split because it alone exceeds the target, split
    on word timings, which the transcriber gave us for exactly this reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.ingest.transcribe import Segment, Word


@dataclass
class Chunk:
    ordinal: int
    start_ms: int
    end_ms: int
    text: str
    confidence: float

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    def timecode(self) -> str:
        """`h:mm:ss` of the start, for a citation a reader can act on."""
        total = self.start_ms // 1000
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chunk_transcript(segments: list[Segment], *, target_chars: int = 1000,
                     overlap_chars: int = 150) -> list[Chunk]:
    """Pack `segments` into chunks of roughly `target_chars`."""
    if not segments:
        return []

    units = _split_oversize(segments, target_chars)
    chunks: list[Chunk] = []
    current: list[Segment] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if not current:
            return
        chunks.append(_build(len(chunks), current))
        # Carry a tail forward so a sentence spanning a boundary is findable
        # from either side. The tail keeps its own timestamps, so the next
        # chunk legitimately starts earlier than its "new" content.
        current = _tail(current, overlap_chars) if overlap_chars > 0 else []
        size = sum(len(s.text) for s in current)

    for seg in units:
        text = seg.text.strip()
        if not text:
            continue
        if size and size + len(text) > target_chars:
            flush()
        current.append(seg)
        size += len(text)

    if current:
        chunks.append(_build(len(chunks), current))
    return chunks


def _build(ordinal: int, segs: list[Segment]) -> Chunk:
    text = " ".join(s.text.strip() for s in segs if s.text.strip())
    total = sum(max(0, s.end_ms - s.start_ms) for s in segs)
    # Duration-weighted, for the same reason Transcript.mean_confidence is: a
    # two-word aside should not counterbalance a minute of difficult audio.
    conf = (sum(s.confidence * max(0, s.end_ms - s.start_ms) for s in segs) / total
            if total else (sum(s.confidence for s in segs) / len(segs)))
    return Chunk(
        ordinal=ordinal,
        start_ms=min(s.start_ms for s in segs),
        end_ms=max(s.end_ms for s in segs),
        text=text,
        confidence=round(conf, 4),
    )


def _tail(segs: list[Segment], overlap_chars: int) -> list[Segment]:
    """The trailing segments of a chunk, up to `overlap_chars`."""
    out: list[Segment] = []
    total = 0
    for s in reversed(segs):
        if total and total + len(s.text) > overlap_chars:
            break
        out.insert(0, s)
        total += len(s.text)
        if total >= overlap_chars:
            break
    # Never carry the entire chunk forward: that makes no progress and the
    # packing loop would not terminate.
    return out if len(out) < len(segs) else out[-1:] if segs else []


def _split_oversize(segments: list[Segment], target_chars: int) -> list[Segment]:
    """Break any single segment longer than the target into word-timed pieces."""
    out: list[Segment] = []
    for seg in segments:
        if len(seg.text) <= target_chars:
            out.append(seg)
            continue
        if not seg.words:
            # No word timings to split on. Splitting the text anyway would
            # invent timestamps, so the segment is kept whole and oversized —
            # an honest big chunk beats a neat wrong one.
            out.append(seg)
            continue
        out.extend(_split_on_words(seg, target_chars))
    return out


def _split_on_words(seg: Segment, target_chars: int) -> list[Segment]:
    pieces: list[Segment] = []
    batch: list[Word] = []
    size = 0
    for w in seg.words:
        if batch and size + len(w.text) + 1 > target_chars:
            pieces.append(_from_words(seg, batch))
            batch, size = [], 0
        batch.append(w)
        size += len(w.text) + 1
    if batch:
        pieces.append(_from_words(seg, batch))
    return pieces or [seg]


def _from_words(seg: Segment, words: list[Word]) -> Segment:
    return Segment(
        start_ms=words[0].start_ms,
        end_ms=words[-1].end_ms,
        text=" ".join(w.text for w in words),
        confidence=sum(w.confidence for w in words) / len(words),
        words=list(words),
        no_speech_prob=seg.no_speech_prob,
        speaker=seg.speaker,
    )
