"""Submitting media, and reading what came of it."""
from __future__ import annotations

import logging
import os
import tempfile

from fastapi import (APIRouter, Depends, File, HTTPException, Query, UploadFile,
                     status)

from app.api.auth import Principal, current_principal
from app.api.schemas import (MediaList, MediaSummary, SegmentOut, SubmitUrl,
                             TranscriptOut)
from app.config import settings
from app.db.models import MediaItem, MediaState, TranscriptSegment
from app.db.session import app_session, owner_session
from app.ingest import resolve
from app.ingest.probe import ProbeError, probe
from app.storage import source_key, storage
from app.jobs import queue
from app.quota import QuotaExceeded, consume, refund, snapshot

log = logging.getLogger("api.media")
router = APIRouter(prefix="/api/media", tags=["media"])

UPLOAD_CHUNK = 1024 * 1024


@router.post("", status_code=status.HTTP_202_ACCEPTED,
             response_model=MediaSummary)
def upload(file: UploadFile = File(...),
                 principal: Principal = Depends(current_principal)):
    """Accept a file and queue it.

    Returns as soon as the row exists. Transcribing an hour of audio takes
    minutes, and holding the request open for it would exceed every proxy
    timeout between here and the browser — the status endpoint is how progress
    is followed.

    A plain function, like every route here that does I/O. Declared `async`, its
    database calls, ffprobe and the storage upload would run on the event loop,
    and every other request on the process would wait for them.
    """
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no filename given")

    with app_session(principal.user_id) as session:
        media = MediaItem(user_id=principal.user_id, source_kind="upload",
                          original_filename=file.filename[:500],
                          state=MediaState.fetching)
        session.add(media)
        session.flush()
        media_id = media.id

    # Buffered to a temp file first, not straight to storage. The size cap has
    # to be enforced against bytes actually seen, and probing needs a seekable
    # file — neither works on a stream being written to a bucket.
    key = source_key(media_id, file.filename)
    tmp = tempfile.NamedTemporaryFile(delete=False,
                                      suffix=_suffix(file.filename))
    dest = tmp.name
    tmp.close()

    written = 0
    try:
        # Streamed rather than read(): a two-gigabyte upload read into memory
        # takes the process down, and Content-Length is a claim by the client
        # rather than a fact, so the cap is enforced against bytes seen.
        with open(dest, "wb") as out:
            while chunk := file.file.read(UPLOAD_CHUNK):
                written += len(chunk)
                if written > settings().max_upload_bytes:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        f"that file is over the "
                        f"{settings().max_upload_bytes // (1024*1024)} MB limit",
                    )
                out.write(chunk)
    except Exception:
        _discard(dest, media_id)
        raise

    if written == 0:
        _discard(dest, media_id)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "that file is empty")

    # Charged now that the length is knowable, and before the job exists, so a
    # user out of allowance never has work queued on their behalf.
    try:
        duration_ms = probe(dest).duration_ms
    except ProbeError as exc:
        _discard(dest, media_id)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    minutes = duration_ms / 60_000
    try:
        with app_session(principal.user_id) as session:
            consume(session, principal.user_id,
                    meter="transcription_minutes", amount=minutes)
    except QuotaExceeded as exc:
        _discard(dest, media_id)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))

    # Handed to storage only once it is known to be real media and paid for.
    # Uploading first would leave orphans in the bucket for every refusal.
    try:
        storage().put(key, dest)
    finally:
        _remove(dest)

    with app_session(principal.user_id) as session:
        media = session.get(MediaItem, media_id)
        media.source_key = key
        media.bytes = written
        media.duration_ms = duration_ms
        media.state = MediaState.pending
        session.add(media)
        session.flush()
        out = MediaSummary.of(media)

    # Enqueued after the upload has landed, so a worker cannot pick the job up
    # while the file is still being written.
    with owner_session() as session:
        queue.enqueue(session, "ingest", {"media_id": media_id})
    log.info("[media] %s uploaded (%d bytes) and queued", media_id, written)
    return out


@router.post("/url", status_code=status.HTTP_202_ACCEPTED,
             response_model=MediaSummary)
def submit_url(body: SubmitUrl,
                     principal: Principal = Depends(current_principal)):
    """Queue media at a URL, if this deployment permits fetching."""
    if not settings().allow_remote_fetch:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "fetching from a URL is disabled on this server; upload the file "
            "instead",
        )
    try:
        resolve.check_url_is_fetchable(body.url)
    except resolve.ResolveError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    # A URL's length is unknown until it downloads. Charging a nominal minute
    # up front stops an empty allowance from queueing a download at all; the
    # fetch handler reconciles to the real duration once it knows it.
    try:
        with app_session(principal.user_id) as session:
            consume(session, principal.user_id,
                    meter="transcription_minutes", amount=1.0)
    except QuotaExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))

    with app_session(principal.user_id) as session:
        media = MediaItem(user_id=principal.user_id, source_kind="url",
                          source_url=body.url, title=body.title,
                          state=MediaState.pending)
        session.add(media)
        session.flush()
        media_id = media.id
        out = MediaSummary.of(media)

    with owner_session() as session:
        queue.enqueue(session, "fetch", {"media_id": media_id})
    return out


@router.get("", response_model=MediaList)
def list_media(principal: Principal = Depends(current_principal),
                     limit: int = Query(default=50, ge=1, le=200),
                     offset: int = Query(default=0, ge=0)):
    with app_session(principal.user_id) as session:
        q = session.query(MediaItem).order_by(MediaItem.created_at.desc())
        total = q.count()
        items = [MediaSummary.of(m) for m in q.offset(offset).limit(limit)]
    return MediaList(items=items, total=total)


@router.get("/{media_id}", response_model=MediaSummary)
def get_media(media_id: str,
                    principal: Principal = Depends(current_principal)):
    with app_session(principal.user_id) as session:
        media = session.get(MediaItem, media_id)
        if media is None:
            # 404 rather than 403 for another tenant's id: the policy already
            # hides the row, and distinguishing the two would confirm that an id
            # exists to someone who cannot see it.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such media")
        return MediaSummary.of(media)


@router.get("/{media_id}/transcript", response_model=TranscriptOut)
def get_transcript(media_id: str,
                         principal: Principal = Depends(current_principal)):
    with app_session(principal.user_id) as session:
        media = session.get(MediaItem, media_id)
        if media is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such media")
        if media.state != MediaState.ready:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"this media is {media.state.value}, not ready",
            )
        segments = (session.query(TranscriptSegment)
                    .filter_by(media_id=media_id)
                    .order_by(TranscriptSegment.ordinal).all())
        return TranscriptOut(
            media_id=media_id,
            language=media.language,
            confidence=media.asr_mean_confidence,
            # Groq returns no per-word probability at all, so its figures are
            # derived from the segment average. Saying so is the difference
            # between a useful number and a misleading one.
            confidence_is_derived=media.asr_backend == "groq",
            segment_count=len(segments),
            segments=[SegmentOut.of(s) for s in segments],
        )


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(media_id: str,
                       principal: Principal = Depends(current_principal)):
    with app_session(principal.user_id) as session:
        media = session.get(MediaItem, media_id)
        if media is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such media")
        session.delete(media)          # segments and chunks cascade
    storage().delete_prefix(media_id)
    return None


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:                         # pragma: no cover
        pass


def _discard(path: str, media_id: str) -> None:
    """Undo a failed upload completely: the buffer and the row."""
    _remove(path)
    with owner_session() as session:
        session.query(MediaItem).filter_by(id=media_id).delete()


def _suffix(filename: str) -> str:
    """The extension, kept only as a hint.

    ffprobe decides what the file actually is. This exists so ffmpeg has
    something familiar to look at, not as a claim about the contents.
    """
    ext = os.path.splitext(filename)[1].lower()
    return ext if len(ext) <= 8 and ext.isascii() else ""
