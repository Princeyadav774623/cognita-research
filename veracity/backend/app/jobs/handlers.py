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
import tempfile
from datetime import datetime, timezone
from typing import Callable

from app.config import settings
from app.db.models import (Analysis, AnalysisState, Claim, MediaItem,
                           MediaState, TranscriptChunk, TranscriptSegment)
from app.ingest import audio as audio_mod
from app.ingest.chunk import chunk_transcript
from app.ingest.probe import probe
from app.ingest.transcribe import transcribe_parts
from app.jobs.queue import LeaseLost

log = logging.getLogger("jobs.handlers")

Heartbeat = Callable[[], None]


class HandlerError(RuntimeError):
    """Something went wrong in a way worth showing the user."""


def _now():
    return datetime.now(timezone.utc)


def _work_dir(media_id: str) -> str:
    """Scratch space for one attempt. Local by definition — ffmpeg needs a real
    path — and deleted when the attempt ends, whatever the backend.

    Unique per attempt, not per media item. Two workers can briefly hold the
    same job — one whose lease lapsed and one that took it over — and on one
    host a shared directory would have them overwrite each other's audio.
    """
    return tempfile.mkdtemp(prefix=f"veracity-{media_id}-")


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

    from app.storage import StorageError, storage

    try:
        if not media.source_key:
            raise HandlerError("this item has no stored file")
        try:
            ctx = storage().local_path(media.source_key)
        except StorageError as exc:
            raise HandlerError(str(exc)) from exc

        with ctx as source:
            # ---- probe ------------------------------------------------------
            _set_state(session, media, MediaState.probing)
            info = probe(source)
            if info.duration_ms > settings().max_duration_seconds * 1000:
                raise HandlerError(
                    f"this is {info.duration_ms // 60000} minutes long; the limit "
                    f"is {settings().max_duration_seconds // 60}"
                )
            # Reconcile: a URL submission was charged a nominal minute before its
            # length could be known. Charge the difference now, or give it back.
            _reconcile_minutes(session, media, info.duration_ms)
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
                    text=seg.text,
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

            # Embedded in one batch rather than per chunk: the model amortises
            # badly across calls, and a two-hour transcript is a few hundred chunks.
            from app.ingest.embed import embed_passages
            vectors = embed_passages([c.text for c in chunks])
            heartbeat()

            for c, vector in zip(chunks, vectors):
                session.add(TranscriptChunk(
                    media_id=media_id, ordinal=c.ordinal,
                    start_ms=c.start_ms, end_ms=c.end_ms, text=c.text,
                    confidence=c.confidence, embedding=vector,
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

    except LeaseLost:
        # Another worker owns this item now; its state is theirs to write.
        raise
    except Exception as exc:
        # Record where it died before re-raising, so the row is informative even
        # while the queue is still deciding whether to retry. Refunds are not
        # made here: see `GIVE_UP`.
        session.rollback()
        media = session.get(MediaItem, media_id)
        if media is not None:
            media.state = MediaState.failed
            media.error = str(exc)[:2000]
            session.add(media)
            session.commit()
        raise
    finally:
        _discard(work)


def _reconcile_minutes(session, media: MediaItem, actual_ms: int) -> None:
    """Settle up once the real duration is known."""
    from app.quota import QuotaExceeded, consume, refund

    charged = (media.duration_ms or 0) / 60_000
    if media.source_kind == "url" and not media.duration_ms:
        charged = 1.0          # the nominal minute taken at submission
    actual = actual_ms / 60_000
    delta = round(actual - charged, 4)
    if abs(delta) < 0.01:
        return
    if delta > 0:
        try:
            consume(session, media.user_id,
                    meter="transcription_minutes", amount=delta)
        except QuotaExceeded as exc:
            raise HandlerError(str(exc)) from exc
    else:
        refund(session, media.user_id,
               meter="transcription_minutes", amount=-delta)


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
        # The pipeline can run for many minutes. Confirm the job is still ours
        # before writing, or a worker that lost it overwrites the new owner.
        heartbeat()

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

    except LeaseLost:
        raise
    except Exception as exc:
        session.rollback()
        analysis = session.get(Analysis, analysis_id)
        if analysis is not None:
            analysis.state = AnalysisState.failed
            analysis.error = str(exc)[:2000]
            session.add(analysis)
            session.commit()
        raise


def fetch(session, payload: dict, heartbeat: Heartbeat) -> None:
    """Download media from a URL, then hand it to ingest.

    A separate job from ingest rather than a first step inside it, for two
    reasons. Downloading fails differently — a dead link, a geo-block, a site
    that changed its markup — and those deserve their own retry budget rather
    than eating the one ingestion needs. And a download that succeeded should
    not be repeated because transcription later failed.
    """
    from app.ingest import resolve as resolve_mod

    media_id = payload["media_id"]
    media = session.get(MediaItem, media_id)
    if media is None:
        raise HandlerError(f"media {media_id} no longer exists")
    from app.storage import source_key, storage

    if media.source_key and storage().exists(media.source_key):
        log.info("[fetch] %s already downloaded", media_id)
    else:
        if not media.source_url:
            raise HandlerError("this item has no URL to fetch")

        _set_state(session, media, MediaState.fetching)
        work = _work_dir(media_id)
        try:
            try:
                got = resolve_mod.fetch(media.source_url, work)
            except resolve_mod.ResolveError as exc:
                media.state = MediaState.failed
                media.error = str(exc)[:2000]
                session.add(media)
                session.commit()
                raise HandlerError(str(exc)) from exc

            key = source_key(media_id, os.path.basename(got.path))
            size = os.path.getsize(got.path)
            storage().put(key, got.path)
        finally:
            _discard(work)

        media.source_key = key
        media.title = media.title or got.title
        media.author = media.author or got.author
        media.source_url = got.webpage_url or media.source_url
        media.bytes = size
        media.state = MediaState.pending
        session.add(media)
        session.commit()
        log.info("[fetch] %s downloaded %s", media_id,
                 os.path.basename(got.path))
    heartbeat()

    # Chained in-process rather than enqueued, so a URL item has exactly one
    # job from submission to ready. A failure in ingest therefore fails the
    # fetch job, which is why the fetch job's give-up refunds the minutes too.
    ingest(session, {"media_id": media_id}, heartbeat)


def _refund_media(session, payload: dict) -> None:
    """Give back the minutes charged for media that will never be ready.

    An upload is charged its measured length when it is received. A URL is
    charged a nominal minute, and reconciled to its real length in the same
    transaction that records `duration_ms` — so an item with no length on
    record owes exactly that minute.
    """
    from app.quota import refund
    media = session.get(MediaItem, payload["media_id"])
    if media is None:
        return
    if media.duration_ms:
        amount = media.duration_ms / 60_000
    elif media.source_kind == "url":
        amount = 1.0
    else:
        amount = 0.0
    refund(session, media.user_id, meter="transcription_minutes",
           amount=amount)


def _refund_analysis(session, payload: dict) -> None:
    """Give back the credits for an analysis that never completed."""
    from app.quota import CREDITS, refund
    analysis = session.get(Analysis, payload["analysis_id"])
    if analysis is None:
        return
    refund(session, analysis.user_id, meter="analysis_credits",
           amount=CREDITS[analysis.mode])


HANDLERS: dict[str, Callable] = {
    "ingest": ingest,
    "fetch": fetch,
    "analyze": analyze,
}

# Run by the queue once a job of that kind has failed for the last time, in the
# same transaction that marks it failed. Keyed by job kind rather than looked up
# by media id, because what matters is which job the user was charged through —
# a URL item is charged through `fetch` and never has an `ingest` job at all.
GIVE_UP: dict[str, Callable] = {
    "ingest": _refund_media,
    "fetch": _refund_media,
    "analyze": _refund_analysis,
}
