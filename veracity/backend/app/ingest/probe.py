"""Read what a media file actually is, before trusting anything about it.

Extension and declared MIME type are claims made by whoever sent the file.
ffprobe reads the container. A file that ffprobe cannot parse is rejected here,
which is cheaper and safer than discovering it three stages later inside an
ffmpeg pipe.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass

FFPROBE = shutil.which("ffprobe") or "ffprobe"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


class ProbeError(RuntimeError):
    """The file is not media we can work with."""


@dataclass(frozen=True)
class MediaInfo:
    duration_ms: int
    container: str
    has_video: bool
    has_audio: bool
    audio_codec: str | None
    video_codec: str | None
    sample_rate: int | None
    channels: int | None
    bit_rate: int | None
    title: str | None
    artist: str | None

    @property
    def duration_seconds(self) -> float:
        return self.duration_ms / 1000.0


def probe(path: str, *, timeout: int = 60) -> MediaInfo:
    """Return what ffprobe says about `path`, or raise ProbeError."""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except FileNotFoundError as exc:
        raise ProbeError(
            "ffprobe is not on the PATH. Install ffmpeg."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffprobe timed out after {timeout}s") from exc

    if out.returncode != 0:
        detail = (out.stderr or "").strip().splitlines()
        raise ProbeError(detail[-1] if detail else "ffprobe failed")

    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError("ffprobe returned output we could not parse") from exc

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    video = next((s for s in streams if s.get("codec_type") == "video"), None)

    if audio is None:
        raise ProbeError(
            "This file has no audio track, so there is nothing to transcribe."
        )

    # Prefer the container's duration; fall back to the audio stream's, because
    # some containers (notably fragmented MP4 and live-recorded WebM) leave the
    # format-level duration empty.
    duration = _as_float(fmt.get("duration")) or _as_float(audio.get("duration"))
    if not duration or duration <= 0:
        # Neither header carries it. This is normal rather than exotic: FLAC
        # written by ffmpeg's segment muxer has no STREAMINFO duration at all,
        # and that is exactly what this pipeline produces when it splits long
        # audio. Decoding is the only way to know, so decode.
        duration = _decoded_duration_seconds(path, timeout=timeout)
    if not duration or duration <= 0:
        raise ProbeError("Could not determine how long this media is")

    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}

    return MediaInfo(
        duration_ms=int(duration * 1000),
        container=(fmt.get("format_name") or "unknown").split(",")[0],
        # A video stream whose codec is an image ("mjpeg", "png") is cover art
        # on an audio file, not video. Treating it as video would have us fetch
        # and store a whole video track that does not exist.
        has_video=bool(video) and video.get("codec_name") not in
        {"mjpeg", "png", "bmp", "gif", "webp"},
        has_audio=True,
        audio_codec=audio.get("codec_name"),
        video_codec=video.get("codec_name") if video else None,
        sample_rate=_as_int(audio.get("sample_rate")),
        channels=_as_int(audio.get("channels")),
        bit_rate=_as_int(fmt.get("bit_rate")),
        title=tags.get("title"),
        artist=tags.get("artist") or tags.get("author"),
    )


def _as_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _decoded_duration_seconds(path: str, *, timeout: int) -> float | None:
    """Decode to nowhere and read how much time went past.

    Costs a full decode, but audio at 16 kHz mono decodes far faster than real
    time, and this only runs when the container declined to say.
    """
    try:
        out = subprocess.run(
            [FFMPEG, "-nostdin", "-i", path, "-vn", "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    # ffmpeg prints progress as it goes; the final "time=" is the total.
    last = None
    for m in re.finditer(r"time=(\d+):(\d\d):(\d\d(?:\.\d+)?)", out.stderr or ""):
        last = m
    if last is None:
        return None
    h, mnt, sec = last.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(sec)
