"""The schema.

Two things are deliberate and worth stating before the tables.

Timestamps are carried by everything derived from the media — segments, words,
chunks, claims. A citation that says "chunk 7" is unverifiable in practice; one
that says 12:34 can be checked in three seconds. Losing the anchor at any stage
means it cannot be recovered later, so nothing in this file drops it.

Confidence from the transcriber travels with the text for the same reason. A
claim assembled out of words the ASR was unsure of must be distinguishable from
one assembled out of words it was certain about, all the way to the point where
something decides whether to fact-check it.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, Enum, Float,
    ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship

from app.config import settings


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MediaState(str, enum.Enum):
    pending = "pending"            # row exists, nothing fetched
    fetching = "fetching"          # downloading or receiving an upload
    probing = "probing"            # reading container metadata
    extracting = "extracting"      # ffmpeg to 16 kHz mono
    transcribing = "transcribing"
    chunking = "chunking"
    ready = "ready"                # answerable
    failed = "failed"


class AnalysisMode(str, enum.Enum):
    summary = "summary"
    deep = "deep"
    report = "report"


class AnalysisState(str, enum.Enum):
    queued = "queued"
    running = "running"
    complete = "complete"
    failed = "failed"


class ClaimVerdict(str, enum.Enum):
    supported = "supported"
    contradicted = "contradicted"
    unsupported = "unsupported"        # searched, found nothing either way
    unclear_audio = "unclear_audio"    # never checked: the ASR was unsure
    not_checkable = "not_checkable"    # opinion, prediction, value judgement


class MediaItem(Base):
    """One piece of media a user asked about."""

    __tablename__ = "media_items"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False, index=True)

    source_kind = Column(String, nullable=False)     # "upload" | "url"
    source_url = Column(Text, nullable=True)
    original_filename = Column(Text, nullable=True)

    title = Column(Text, nullable=True)
    author = Column(Text, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)

    state = Column(Enum(MediaState, name="media_state"),
                   nullable=False, default=MediaState.pending)
    error = Column(Text, nullable=True)

    duration_ms = Column(BigInteger, nullable=True)
    container = Column(String, nullable=True)
    has_video = Column(Boolean, nullable=False, default=False)
    bytes = Column(BigInteger, nullable=True)

    # Where the normalised audio landed. Kept separate from the original so the
    # original can be discarded once transcription succeeds.
    audio_path = Column(Text, nullable=True)
    source_path = Column(Text, nullable=True)

    language = Column(String, nullable=True)
    asr_backend = Column(String, nullable=True)
    asr_model = Column(String, nullable=True)
    # Proportion of words the transcriber was confident about. A low number here
    # is a ceiling on every downstream verdict, and the interface says so.
    asr_mean_confidence = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    ready_at = Column(DateTime(timezone=True), nullable=True)

    segments = relationship("TranscriptSegment", back_populates="media",
                            cascade="all, delete-orphan")
    chunks = relationship("TranscriptChunk", back_populates="media",
                          cascade="all, delete-orphan")
    analyses = relationship("Analysis", back_populates="media",
                            cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_media_user_created", "user_id", "created_at"),
        CheckConstraint("source_kind in ('upload','url')", name="ck_media_source_kind"),
    )


class TranscriptSegment(Base):
    """One utterance as the transcriber produced it, before any re-chunking.

    Kept verbatim and separately from chunks so the original timing survives:
    chunking is a lossy re-grouping, and a reader following a citation back to
    the media needs the timing the transcriber actually emitted.
    """

    __tablename__ = "transcript_segments"

    id = Column(String, primary_key=True, default=_uuid)
    media_id = Column(String, ForeignKey("media_items.id", ondelete="CASCADE"),
                      nullable=False)
    ordinal = Column(Integer, nullable=False)

    start_ms = Column(BigInteger, nullable=False)
    end_ms = Column(BigInteger, nullable=False)
    text = Column(Text, nullable=False)

    speaker = Column(String, nullable=True)      # set only if diarization ran
    confidence = Column(Float, nullable=True)    # mean over the words
    # [{"w": "ninety", "s": 12340, "e": 12520, "c": 0.81}, ...]
    words = Column(JSONB, nullable=True)

    media = relationship("MediaItem", back_populates="segments")

    __table_args__ = (
        UniqueConstraint("media_id", "ordinal", name="uq_segment_ordinal"),
        Index("ix_segment_media_start", "media_id", "start_ms"),
        CheckConstraint("end_ms >= start_ms", name="ck_segment_span"),
    )


class TranscriptChunk(Base):
    """A retrieval unit: several segments grouped to a target size, still timed."""

    __tablename__ = "transcript_chunks"

    id = Column(String, primary_key=True, default=_uuid)
    media_id = Column(String, ForeignKey("media_items.id", ondelete="CASCADE"),
                      nullable=False)
    ordinal = Column(Integer, nullable=False)

    start_ms = Column(BigInteger, nullable=False)
    end_ms = Column(BigInteger, nullable=False)
    text = Column(Text, nullable=False)
    speakers = Column(JSONB, nullable=True)
    confidence = Column(Float, nullable=True)

    embedding = Column(Vector(settings().embedding_dim), nullable=True)

    media = relationship("MediaItem", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("media_id", "ordinal", name="uq_chunk_ordinal"),
        Index("ix_chunk_media_start", "media_id", "start_ms"),
        CheckConstraint("end_ms >= start_ms", name="ck_chunk_span"),
    )


class Analysis(Base):
    """One run of one mode over one media item."""

    __tablename__ = "analyses"

    id = Column(String, primary_key=True, default=_uuid)
    media_id = Column(String, ForeignKey("media_items.id", ondelete="CASCADE"),
                      nullable=False)
    user_id = Column(String, nullable=False, index=True)

    mode = Column(Enum(AnalysisMode, name="analysis_mode"), nullable=False)
    state = Column(Enum(AnalysisState, name="analysis_state"),
                   nullable=False, default=AnalysisState.queued)
    error = Column(Text, nullable=True)

    summary_md = Column(Text, nullable=True)
    key_points = Column(JSONB, nullable=True)
    topics = Column(JSONB, nullable=True)

    # Populated at report depth only.
    overall_confidence = Column(Float, nullable=True)
    confidence_factors = Column(JSONB, nullable=True)
    perspectives = Column(JSONB, nullable=True)

    tokens_used = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    media = relationship("MediaItem", back_populates="analyses")
    claims = relationship("Claim", back_populates="analysis",
                          cascade="all, delete-orphan")

    __table_args__ = (Index("ix_analysis_media_mode", "media_id", "mode"),)


class Claim(Base):
    """A checkable proposition extracted from what someone said.

    `spoken_text` is what was actually said; `proposition` is the normalised,
    self-contained form that can be searched for. Keeping both is what lets the
    interface show a verdict next to the words that produced it, and what makes
    a bad normalisation visible rather than silent.
    """

    __tablename__ = "claims"

    id = Column(String, primary_key=True, default=_uuid)
    analysis_id = Column(String, ForeignKey("analyses.id", ondelete="CASCADE"),
                         nullable=False)
    ordinal = Column(Integer, nullable=False)

    start_ms = Column(BigInteger, nullable=False)
    end_ms = Column(BigInteger, nullable=False)
    speaker = Column(String, nullable=True)

    spoken_text = Column(Text, nullable=False)
    proposition = Column(Text, nullable=False)
    asr_confidence = Column(Float, nullable=True)

    verdict = Column(Enum(ClaimVerdict, name="claim_verdict"), nullable=False,
                     default=ClaimVerdict.unsupported)
    verdict_confidence = Column(Float, nullable=True)
    reasoning = Column(Text, nullable=True)

    # Sources found by searching for this claim specifically, not sources the
    # summariser already had. Agreement with one's own summary is weak evidence.
    evidence = Column(JSONB, nullable=True)
    independently_corroborated = Column(Boolean, nullable=False, default=False)
    counter_evidence = Column(JSONB, nullable=True)

    analysis = relationship("Analysis", back_populates="claims")

    __table_args__ = (
        UniqueConstraint("analysis_id", "ordinal", name="uq_claim_ordinal"),
        Index("ix_claim_analysis_start", "analysis_id", "start_ms"),
    )


class Job(Base):
    """A unit of background work.

    Durable and in Postgres rather than in memory or in a broker. Cognita runs
    ingestion inside the web process, and a restart mid-upload strands the row —
    a defect its own report records. This is the fix, not a mitigation: a lease
    expires and the job is picked up again by whoever is next to poll.
    """

    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=_uuid)
    kind = Column(String, nullable=False)          # "ingest" | "analyze"
    payload = Column(JSONB, nullable=False)

    state = Column(String, nullable=False, default="queued")
    priority = Column(Integer, nullable=False, default=100)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)

    run_after = Column(DateTime(timezone=True), nullable=False, default=_now)
    leased_until = Column(DateTime(timezone=True), nullable=True)
    leased_by = Column(String, nullable=True)

    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The claim query orders by this and filters on state; without it the
        # worker table-scans once the archive of finished jobs is large.
        Index("ix_jobs_claimable", "state", "priority", "run_after"),
        CheckConstraint("state in ('queued','running','done','failed')",
                        name="ck_job_state"),
    )
