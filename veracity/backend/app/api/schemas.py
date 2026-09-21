"""Request and response shapes.

Responses are hand-built rather than serialised straight off the ORM. A media
row holds a filesystem path and a transcription backend name; neither belongs in
an API response, and "serialise the model" is how they end up there.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def timecode(ms: int) -> str:
    """`h:mm:ss` — what a citation needs to be actionable."""
    total = max(0, ms) // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class SubmitUrl(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    title: str | None = Field(default=None, max_length=500)

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        v = v.strip()
        if not v.lower().startswith(("http://", "https://")):
            # file:// and friends would make this a local file read reachable
            # from the internet.
            raise ValueError("only http(s) URLs are accepted")
        return v


class MediaSummary(BaseModel):
    id: str
    state: str
    source_kind: str
    title: str | None = None
    author: str | None = None
    filename: str | None = None
    url: str | None = None
    duration_ms: int | None = None
    duration: str | None = None
    has_video: bool = False
    language: str | None = None
    transcription_confidence: float | None = None
    error: str | None = None
    created_at: datetime | None = None
    ready_at: datetime | None = None

    @classmethod
    def of(cls, m) -> "MediaSummary":
        return cls(
            id=m.id,
            state=m.state.value if hasattr(m.state, "value") else str(m.state),
            source_kind=m.source_kind,
            title=m.title,
            author=m.author,
            filename=m.original_filename,
            url=m.source_url,
            duration_ms=m.duration_ms,
            duration=timecode(m.duration_ms) if m.duration_ms else None,
            has_video=bool(m.has_video),
            language=m.language,
            transcription_confidence=m.asr_mean_confidence,
            error=m.error,
            created_at=m.created_at,
            ready_at=m.ready_at,
        )


class SegmentOut(BaseModel):
    ordinal: int
    start_ms: int
    end_ms: int
    at: str
    text: str
    speaker: str | None = None
    confidence: float | None = None

    @classmethod
    def of(cls, s) -> "SegmentOut":
        return cls(ordinal=s.ordinal, start_ms=s.start_ms, end_ms=s.end_ms,
                   at=timecode(s.start_ms), text=s.text, speaker=s.speaker,
                   confidence=s.confidence)


class TranscriptOut(BaseModel):
    media_id: str
    language: str | None
    confidence: float | None
    # Stated explicitly rather than left for the reader to infer from a number
    # near 1.0. Whisper reports a per-segment average log-probability, not a
    # per-word probability, so this is derived unless the backend measured it.
    confidence_is_derived: bool
    segment_count: int
    segments: list[SegmentOut]


class MediaList(BaseModel):
    items: list[MediaSummary]
    total: int
