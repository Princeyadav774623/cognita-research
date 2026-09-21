"""Turn arbitrary media into audio a transcriber will accept.

Two jobs. Normalise — 16 kHz mono is what every Whisper-family model wants, and
feeding it anything else means the model resamples internally while you pay to
upload samples that get discarded. Then split, because hosted transcription caps
the upload size and an hour of audio exceeds it however it is encoded.

Splitting is where timing is most easily lost, so it does not use ffmpeg.

ffmpeg was the obvious tool and it was wrong twice. Its `segment` muxer leaves a
sub-second remnant file and stamps every part's FLAC header with the *source's*
total sample count, so probing part four of a thirty-second file reports thirty
seconds. Cutting explicitly with `-ss`/`-t` avoided that and introduced a worse
failure: on ffmpeg 9.0.2 some offsets simply produce no packets — 13.9 s and
14.1 s cut fine, 14.0 s fails with "Conversion failed". A citation that is
silently wrong by minutes is the one defect this product cannot ship.

So ffmpeg decodes once, to a single 16 kHz mono WAV, and the split is byte
arithmetic over PCM frames. At 16 kHz, 16-bit, mono a frame is exactly two bytes
and a second is exactly 32,000 of them, which makes every offset exact by
construction rather than by trust.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import wave
from dataclasses import dataclass

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2                      # 16-bit PCM
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH   # 32,000

# A remnant shorter than this carries no speech and costs a whole round trip.
MIN_PART_MS = 200


class AudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioPart:
    path: str
    offset_ms: int          # where this part begins in the original media
    duration_ms: int

    @property
    def bytes(self) -> int:
        return os.path.getsize(self.path)


def extract(src: str, dest: str, *, timeout: int = 3600) -> str:
    """Write `src`'s audio to `dest` as a 16 kHz mono WAV.

    WAV rather than a compressed format because the split below indexes into
    raw frames. It is larger on disk, briefly; parts are what get uploaded and
    the caller is free to delete this once they exist.
    """
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    _run([
        FFMPEG, "-nostdin", "-y",
        "-i", src,
        "-vn",                          # drop video; only audio is transcribed
        "-map", "0:a:0",                # first audio stream, not commentary
        "-ac", str(CHANNELS),
        "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        "-f", "wav",
        dest,
    ], timeout=timeout, what="extract audio")

    if not os.path.exists(dest) or os.path.getsize(dest) == 0:
        raise AudioError("ffmpeg produced no audio")
    return dest


def segment(src: str, out_dir: str, *, seconds: int,
            max_bytes: int, timeout: int = 3600) -> list[AudioPart]:
    """Split a 16 kHz mono WAV into parts, each under `max_bytes`.

    Returns a single part covering the whole file when it already fits, so a
    short clip costs no extra work.
    """
    os.makedirs(out_dir, exist_ok=True)

    if os.path.getsize(src) <= max_bytes:
        return [AudioPart(path=src, offset_ms=0,
                          duration_ms=_wav_duration_ms(src))]

    # Header aside, a part of `seconds` is exactly this many bytes, so choose a
    # length that cannot overshoot the cap rather than checking afterwards.
    header_slack = 1024
    max_seconds = (max_bytes - header_slack) // BYTES_PER_SECOND
    if max_seconds < 1:
        raise AudioError(
            f"max_bytes={max_bytes} cannot hold even one second of 16 kHz audio"
        )
    step_seconds = min(seconds, max_seconds)

    parts: list[AudioPart] = []
    try:
        with wave.open(src, "rb") as wav:
            _require_pcm(wav, src)
            rate = wav.getframerate()
            total_frames = wav.getnframes()
            step_frames = step_seconds * rate

            index = 0
            while True:
                start_frame = index * step_frames
                if start_frame >= total_frames:
                    break
                frames = wav.readframes(step_frames)
                if not frames:
                    break
                n_frames = len(frames) // (wav.getsampwidth() * wav.getnchannels())
                duration_ms = round(n_frames * 1000 / rate)
                if duration_ms < MIN_PART_MS:
                    break

                path = os.path.join(out_dir, f"part-{index:05d}.wav")
                with wave.open(path, "wb") as out:
                    out.setnchannels(wav.getnchannels())
                    out.setsampwidth(wav.getsampwidth())
                    out.setframerate(rate)
                    out.writeframes(frames)

                parts.append(AudioPart(
                    path=path,
                    offset_ms=round(start_frame * 1000 / rate),
                    duration_ms=duration_ms,
                ))
                index += 1
    except wave.Error as exc:
        raise AudioError(f"{os.path.basename(src)} is not a readable WAV: {exc}") from exc

    if not parts:
        raise AudioError("splitting produced no parts")

    oversize = [p for p in parts if p.bytes > max_bytes]
    if oversize:  # pragma: no cover - the arithmetic above rules this out
        raise AudioError(
            f"{len(oversize)} part(s) exceed the {max_bytes} byte limit despite "
            f"a {step_seconds}s step"
        )
    return parts


def _require_pcm(wav: wave.Wave_read, path: str) -> None:
    if wav.getsampwidth() != SAMPLE_WIDTH or wav.getnchannels() != CHANNELS:
        raise AudioError(
            f"{os.path.basename(path)} is {wav.getnchannels()}ch/"
            f"{wav.getsampwidth() * 8}-bit; splitting expects mono 16-bit PCM. "
            "Run extract() first."
        )


def _wav_duration_ms(path: str) -> int:
    try:
        with wave.open(path, "rb") as wav:
            return round(wav.getnframes() * 1000 / wav.getframerate())
    except wave.Error:
        # Not a WAV — fall back to probing, so callers can still pass a file
        # they extracted some other way.
        from app.ingest.probe import probe
        return probe(path).duration_ms


def _run(cmd: list[str], *, timeout: int, what: str) -> None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise AudioError("ffmpeg is not on the PATH. Install ffmpeg.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"ffmpeg timed out after {timeout}s while trying to "
                         f"{what}") from exc
    if out.returncode != 0:
        # ffmpeg's last stderr line is the cause; everything above it is banner.
        tail = (out.stderr or "").strip().splitlines()
        raise AudioError(f"ffmpeg failed to {what}: "
                         f"{tail[-1] if tail else 'no detail'}")
