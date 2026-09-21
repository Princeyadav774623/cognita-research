"""What a job actually does.

Handlers are plain functions taking (session, payload, heartbeat). They own no
transaction policy and no retry policy — the worker owns both — so a handler can
be called directly from a test without a queue in the way.

`heartbeat` is passed in rather than imported because long stages need to call
it. Transcribing an hour of audio can outlast any lease short enough to recover
quickly from a crash; extending the lease as the work proceeds gives both.
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Callable

from app.config import settings
from app.db.models import (Analysis, AnalysisState, Claim, MediaItem,
                           MediaState, TranscriptChunk, TranscriptSegment)
from app.ingest import audio as audio_mod
from app.ingest.chunk import chunk_transcript
from app.ingest.probe import probe
from app.ingest.transcribe import transcribe_parts

log = logging.getLogger("jobs.handlers")

Heartbeat = Callable[[], None]


class HandlerError(RuntimeError):
    """Something went wrong in a way worth showing the user."""


def _now():
    return datetime.now(timezone.utc)


def _work_dir(media_id: str) -> str:
    return os.path.join(settings().media_root, media_id)


def ingest(session, payload: dict, heartbeat: Heartbeat) -> None:
    """Take a media item from `pending` to `ready`.

    Each stage writes its state before starting, so a crash leaves a row that
    says which stage it died in rather than a generic failure. The states are
    the ones the interface shows, which is why they are this granular.
    """
    media_id = payload["media_id"]
    media = session.get(MediaItem, media_id)
    if media is None:
        raise HandlerError(f"media {media_id} no longer exists")
    if media.state == MediaState.ready:
        log.info("[ingest] %s already ready, nothing to do", media_id)
        return

    work = _work_dir(media_id)
    os.makedirs(work, exist_ok=True)

    try:
        source = media.source_path
        if not source or not os.path.exists(source):
            raise HandlerError("the source file is missing")

        # ---- probe ------------------------------------------------------
        _set_state(session, media, MediaState.probing)
        info = probe(source)
        if info.duration_ms > settings().max_duration_seconds * 1000:
            raise HandlerError(
                f"this is {info.duration_ms // 60000} minutes long; the limit "
                f"is {settings().max_duration_seconds // 60}"
            )
        media.duration_ms = info.duration_ms
        media.container = info.container
        media.has_video = info.has_video
        media.bytes = os.path.getsize(source)
        media.title = media.title or info.title
        media.author = media.author or info.artist
        session.add(media)
        session.commit()
        heartbeat()

        # ---- audio ------------------------------------------------------
        _set_state(session, media, MediaState.extracting)
        wav = audio_mod.extract(source, os.path.join(work, "audio.wav"))
        media.audio_path = wav
        session.add(media)
        session.commit()
        heartbeat()

        parts = audio_mod.segment(
            wav, os.path.join(work, "parts"),
            seconds=settings().asr_segment_seconds,
            max_bytes=settings().asr_max_upload_bytes,
        )
        log.info("[ingest] %s split into %d part(s)", media_id, len(parts))

        # ---- transcribe -------------------------------------------------
        _set_state(session, media, MediaState.transcribing)
        transcript = transcribe_parts(parts, language=media.language)
        if not transcript.segments:
            raise HandlerError(
                "nothing was transcribed — the audio may be silent or music only"
            )
        heartbeat()

        media.language = transcript.language
        media.asr_backend = transcript.backend
        media.asr_model = transcript.model
        media.asr_mean_confidence = round(transcript.mean_confidence, 4)

        session.query(TranscriptSegment).filter_by(media_id=media_id).delete()
        for i, seg in enumerate(transcript.segments):
            session.add(TranscriptSegment(
                media_id=media_id, ordinal=i,
                start_ms=seg.start_ms, end_ms=seg.end_ms,
                text=seg.text, speaker=seg.speaker,
                confidence=round(seg.confidence, 4),
                words=[{"w": w.text, "s": w.start_ms, "e": w.end_ms,
                        "c": round(w.confidence, 3), "m": w.measured}
                       for w in seg.words] or None,
            ))
        session.commit()
        heartbeat()

        # ---- chunk ------------------------------------------------------
        _set_state(session, media, MediaState.chunking)
        chunks = chunk_transcript(
            transcript.segments,
            target_chars=settings().chunk_target_chars,
            overlap_chars=settings().chunk_overlap_chars,
        )
        session.query(TranscriptChunk).filter_by(media_id=media_id).delete()
        for c in chunks:
            session.add(TranscriptChunk(
                media_id=media_id, ordinal=c.ordinal,
                start_ms=c.start_ms, end_ms=c.end_ms, text=c.text,
                confidence=c.confidence, speakers=c.speakers or None,
            ))
        session.commit()

        # ---- done -------------------------------------------------------
        media.state = MediaState.ready
        media.ready_at = _now()
        media.error = None
        session.add(media)
        session.commit()
        log.info("[ingest] %s ready: %d segments, %d chunks, confidence %.3f",
                 media_id, len(transcript.segments), len(chunks),
                 transcript.mean_confidence)

        # The normalised audio is large and nothing downstream reads it again.
        _discard(os.path.join(work, "parts"))
        _discard(wav)
        media.audio_path = None
        session.add(media)
        session.commit()

    except Exception as exc:
        # Record where it died before re-raising, so the row is informative even
        # while the queue is still deciding whether to retry.
        media = session.get(MediaItem, media_id)
        if media is not None:
            media.state = MediaState.failed
            media.error = str(exc)[:2000]
            session.add(media)
            session.commit()
        raise


def _set_state(session, media: MediaItem, state: MediaState) -> None:
    media.state = state
    session.add(media)
    session.commit()


def _discard(path: str) -> None:
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
    except OSError as exc:                      # pragma: no cover
        log.warning("[ingest] could not clean up %s: %s", path, exc)


def analyze(session, payload: dict, heartbeat: Heartbeat) -> None:
    """Run one analysis at one depth and persist it.

    The analysis row exists before the work starts, so the interface has
    something to show a spinner against and a failure has somewhere to land.
    """
    from app.analysis.pipeline import run as run_pipeline
    from app.llm import ledger

    analysis_id = payload["analysis_id"]
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HandlerError(f"analysis {analysis_id} no longer exists")
    if analysis.state == AnalysisState.complete:
        log.info("[analyze] %s already complete", analysis_id)
        return

    media = session.get(MediaItem, analysis.media_id)
    if media is None or media.state != MediaState.ready:
        raise HandlerError("the media is not transcribed yet")

    analysis.state = AnalysisState.running
    analysis.error = None
    session.add(analysis)
    session.commit()

    try:
        segments = (session.query(TranscriptSegment)
                    .filter_by(media_id=media.id)
                    .order_by(TranscriptSegment.ordinal).all())
        heartbeat()

        with ledger() as book:
            out = run_pipeline(segments, analysis.mode,
                               asr_confidence=media.asr_mean_confidence)

        analysis.summary_md = out.get("summary") or None
        analysis.key_points = out.get("key_points") or None
        analysis.topics = out.get("topics") or None
        analysis.overall_confidence = out.get("overall_confidence")
        analysis.confidence_factors = out.get("confidence_factors")
        analysis.perspectives = out.get("perspectives") or None
        analysis.tokens_used = book.total
        analysis.cost_usd = book.cost_usd()

        session.query(Claim).filter_by(analysis_id=analysis_id).delete()
        for row in out.get("claims") or []:
            session.add(Claim(analysis_id=analysis_id, **row))

        analysis.state = AnalysisState.complete
        analysis.completed_at = _now()
        session.add(analysis)
        session.commit()
        log.info("[analyze] %s %s complete: %d claims, %d tokens, $%.4f",
                 analysis.mode.value, analysis_id,
                 len(out.get("claims") or []), book.total, book.cost_usd())

    except Exception as exc:
        analysis = session.get(Analysis, analysis_id)
        if analysis is not None:
            analysis.state = AnalysisState.failed
            analysis.error = str(exc)[:2000]
            session.add(analysis)
            session.commit()
        raise


HANDLERS: dict[str, Callable] = {
    "ingest": ingest,
    "analyze": analyze,
}
