"""Speech to timed, confidence-carrying text.

Two backends behind one protocol. Groq's hosted Whisper is the default because
it needs no model download and no GPU, and the key is already in the
environment. faster-whisper is there for deployments where the audio must not
leave the machine.

The part that matters more than either: every word carries a confidence, and it
is honest about where that number came from. Whisper does not emit a true
per-word probability — it emits a per-segment average log-probability, and the
per-word figure below is derived from it. A derived number that is labelled as
derived is useful; one presented as a measurement is a lie that later makes a
fact-checker sound certain about a word nobody said.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Protocol

from app.config import settings

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class TranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Word:
    text: str
    start_ms: int
    end_ms: int
    confidence: float
    # True when the model reported a probability for this word; False when the
    # figure was derived from the enclosing segment. The distinction survives
    # into the database so a verdict can say which it relied on.
    measured: bool = False


@dataclass
class Segment:
    start_ms: int
    end_ms: int
    text: str
    confidence: float
    words: list[Word] = field(default_factory=list)
    no_speech_prob: float | None = None
    speaker: str | None = None

    def shifted(self, offset_ms: int) -> "Segment":
        """Return this segment repositioned into the original media's timeline.

        Audio is transcribed in parts, and every part starts at zero. Forgetting
        to shift is the single easiest way to make every citation in the product
        wrong by minutes, so it is a method here rather than arithmetic scattered
        across the caller.
        """
        if offset_ms == 0:
            return self
        return Segment(
            start_ms=self.start_ms + offset_ms,
            end_ms=self.end_ms + offset_ms,
            text=self.text,
            confidence=self.confidence,
            words=[Word(w.text, w.start_ms + offset_ms, w.end_ms + offset_ms,
                        w.confidence, w.measured) for w in self.words],
            no_speech_prob=self.no_speech_prob,
            speaker=self.speaker,
        )


@dataclass
class Transcript:
    segments: list[Segment]
    language: str | None
    backend: str
    model: str

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())

    @property
    def mean_confidence(self) -> float:
        """Duration-weighted, not segment-weighted.

        A one-word interjection and a forty-second monologue are one segment
        each; averaging them equally lets a couple of confident "yeah"s mask a
        long stretch the model struggled with.
        """
        total = sum(max(0, s.end_ms - s.start_ms) for s in self.segments)
        if not total:
            return 0.0
        return sum(s.confidence * max(0, s.end_ms - s.start_ms)
                   for s in self.segments) / total


# Whisper *reports* a language as an English name ("English") and *accepts* one
# as an ISO 639-1 code ("en"). Feeding what part one detected straight into part
# two therefore fails the whole job with "unsupported language: English" — and
# only for multi-part media, which is to say only for the long files that matter
# most. Report the name, forward the code.
_LANGUAGE_CODES = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de",
    "italian": "it", "portuguese": "pt", "dutch": "nl", "russian": "ru",
    "polish": "pl", "turkish": "tr", "arabic": "ar", "hindi": "hi",
    "bengali": "bn", "urdu": "ur", "tamil": "ta", "telugu": "te",
    "marathi": "mr", "gujarati": "gu", "kannada": "kn", "malayalam": "ml",
    "punjabi": "pa", "chinese": "zh", "japanese": "ja", "korean": "ko",
    "vietnamese": "vi", "thai": "th", "indonesian": "id", "malay": "ms",
    "swedish": "sv", "norwegian": "no", "danish": "da", "finnish": "fi",
    "czech": "cs", "greek": "el", "hebrew": "he", "ukrainian": "uk",
    "romanian": "ro", "hungarian": "hu", "catalan": "ca", "persian": "fa",
}


def language_code(language: str | None) -> str | None:
    """An ISO 639-1 code for `language`, or None if we cannot be sure.

    None is a safe answer: the transcriber detects the language itself, so the
    only cost of withholding it is a little accuracy on the next part. Guessing
    wrong costs the whole job.
    """
    if not language:
        return None
    value = language.strip().lower()
    if len(value) == 2 and value.isalpha():
        return value
    return _LANGUAGE_CODES.get(value)


class Transcriber(Protocol):
    name: str

    def transcribe(self, path: str, *, language: str | None = None) -> Transcript:
        ...


def _confidence_from_logprob(avg_logprob: float | None) -> float:
    """Whisper's average log-probability, mapped to something readable.

    exp(avg_logprob) is the geometric mean token probability. It is not
    calibrated — Whisper is famously overconfident on hallucinated runs — so it
    is used only as a relative signal and as a floor for "do not fact-check
    this", never as a probability shown to a user.
    """
    if avg_logprob is None:
        return 0.5
    return max(0.0, min(1.0, math.exp(avg_logprob)))


# --------------------------------------------------------------------- Groq
class GroqTranscriber:
    name = "groq"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        cfg = settings()
        self.model = model or cfg.asr_model
        self._key = api_key or cfg.groq_api_key

    def transcribe(self, path: str, *, language: str | None = None) -> Transcript:
        import httpx

        size = os.path.getsize(path)
        if size > settings().asr_max_upload_bytes:
            raise TranscriptionError(
                f"{os.path.basename(path)} is {size:,} bytes, over the "
                f"{settings().asr_max_upload_bytes:,} byte upload limit. "
                "It should have been segmented before reaching here."
            )

        code = language_code(language)
        data = {
            "model": self.model,
            "response_format": "verbose_json",
            # Both granularities: words give the anchors, segments give the
            # log-probabilities that words are scored from.
            "timestamp_granularities[]": ["word", "segment"],
        }
        if code:
            data["language"] = code

        try:
            with open(path, "rb") as fh:
                resp = httpx.post(
                    GROQ_TRANSCRIBE_URL,
                    headers={"Authorization": f"Bearer {self._key}"},
                    files={"file": (os.path.basename(path), fh, "audio/flac")},
                    data=data,
                    timeout=httpx.Timeout(600.0, connect=30.0),
                )
        except httpx.HTTPError as exc:
            raise TranscriptionError(f"could not reach the transcriber: {exc}") from exc

        if resp.status_code == 429:
            raise TranscriptionError(
                "transcription rate limit reached: " + _brief(resp.text)
            )
        if resp.status_code >= 400:
            raise TranscriptionError(
                f"transcriber returned {resp.status_code}: {_brief(resp.text)}"
            )

        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            raise TranscriptionError("transcriber returned unparseable JSON") from exc

        return _from_verbose_json(payload, backend=self.name, model=self.model)


# ------------------------------------------------------------ faster-whisper
class LocalTranscriber:
    name = "faster-whisper"

    def __init__(self, model: str | None = None):
        self.model = model or settings().asr_local_model
        self._impl = None

    def _load(self):
        if self._impl is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise TranscriptionError(
                    "ASR_BACKEND=faster-whisper but faster-whisper is not "
                    "installed. pip install faster-whisper"
                ) from exc
            self._impl = WhisperModel(self.model, device="auto",
                                      compute_type="int8")
        return self._impl

    def transcribe(self, path: str, *, language: str | None = None) -> Transcript:
        model = self._load()
        segments, info = model.transcribe(
            path, language=language, word_timestamps=True,
            vad_filter=True,          # skip silence rather than hallucinate into it
        )
        out: list[Segment] = []
        for s in segments:
            seg_conf = _confidence_from_logprob(getattr(s, "avg_logprob", None))
            words = []
            for w in (getattr(s, "words", None) or []):
                # faster-whisper does give a real per-word probability.
                prob = getattr(w, "probability", None)
                words.append(Word(
                    text=w.word.strip(),
                    start_ms=int(w.start * 1000),
                    end_ms=int(w.end * 1000),
                    confidence=float(prob) if prob is not None else seg_conf,
                    measured=prob is not None,
                ))
            out.append(Segment(
                start_ms=int(s.start * 1000), end_ms=int(s.end * 1000),
                text=s.text.strip(), confidence=seg_conf, words=words,
                no_speech_prob=getattr(s, "no_speech_prob", None),
            ))
        return Transcript(segments=out,
                          language=getattr(info, "language", language),
                          backend=self.name, model=self.model)


def _from_verbose_json(payload: dict, *, backend: str, model: str) -> Transcript:
    """Build a Transcript from an OpenAI-shaped verbose_json response.

    Word and segment lists arrive separately and are not cross-referenced, so
    words are attached to segments by their timing. A word that falls in no
    segment still keeps its own timing and a neutral confidence rather than
    being dropped — losing words silently would understate how much was said.
    """
    raw_segments = payload.get("segments") or []
    raw_words = payload.get("words") or []

    segments: list[Segment] = []
    for s in raw_segments:
        conf = _confidence_from_logprob(s.get("avg_logprob"))
        segments.append(Segment(
            start_ms=int(float(s.get("start", 0)) * 1000),
            end_ms=int(float(s.get("end", 0)) * 1000),
            text=(s.get("text") or "").strip(),
            confidence=conf,
            no_speech_prob=s.get("no_speech_prob"),
        ))

    if not segments and payload.get("text"):
        # Some models return only flat text. Better one untimed segment than
        # nothing; downstream treats a zero-width span as "cannot cite".
        segments = [Segment(start_ms=0, end_ms=0,
                            text=payload["text"].strip(), confidence=0.5)]

    for w in raw_words:
        start_ms = int(float(w.get("start", 0)) * 1000)
        end_ms = int(float(w.get("end", 0)) * 1000)
        host = _host_segment(segments, start_ms, end_ms)
        prob = w.get("probability")
        word = Word(
            text=(w.get("word") or "").strip(),
            start_ms=start_ms, end_ms=end_ms,
            confidence=float(prob) if prob is not None
            else (host.confidence if host else 0.5),
            measured=prob is not None,
        )
        if host is not None:
            host.words.append(word)
        else:
            segments.append(Segment(start_ms=start_ms, end_ms=end_ms,
                                    text=word.text, confidence=word.confidence,
                                    words=[word]))

    segments.sort(key=lambda s: (s.start_ms, s.end_ms))
    return Transcript(segments=segments, language=payload.get("language"),
                      backend=backend, model=model)


# Whisper's word list and segment list are produced independently, and their
# boundaries do not line up: a word can start a few milliseconds before the
# segment that contains it, or land in the gap between two. Requiring
# containment therefore orphans real words, and an orphan becomes a one-word
# segment whose text is already inside its neighbour — which is how a transcript
# ends up reading "It It was completed in 1889".
_ORPHAN_TOLERANCE_MS = 2_000


def _host_segment(segments: list[Segment], start_ms: int,
                  end_ms: int) -> Segment | None:
    """The segment a word belongs to: most overlap, else nearest within reach."""
    if not segments:
        return None

    best, best_overlap = None, 0
    for s in segments:
        overlap = min(end_ms, s.end_ms) - max(start_ms, s.start_ms)
        if overlap > best_overlap:
            best, best_overlap = s, overlap
    if best is not None:
        return best

    nearest, nearest_gap = None, None
    for s in segments:
        gap = start_ms - s.end_ms if start_ms > s.end_ms else s.start_ms - end_ms
        if gap >= 0 and (nearest_gap is None or gap < nearest_gap):
            nearest, nearest_gap = s, gap
    if nearest is not None and nearest_gap is not None \
            and nearest_gap <= _ORPHAN_TOLERANCE_MS:
        return nearest
    return None


def transcribe_parts(parts, *, language: str | None = None,
                     transcriber: Transcriber | None = None) -> Transcript:
    """Transcribe audio parts and stitch them back onto one timeline."""
    t = transcriber or get_transcriber()
    all_segments: list[Segment] = []
    hint = language_code(language)
    reported = language
    for part in parts:
        piece = t.transcribe(part.path, language=hint)
        reported = reported or piece.language
        hint = hint or language_code(piece.language)
        all_segments.extend(s.shifted(part.offset_ms) for s in piece.segments)
    all_segments.sort(key=lambda s: (s.start_ms, s.end_ms))
    return Transcript(segments=all_segments, language=reported,
                      backend=t.name, model=getattr(t, "model", "?"))


def get_transcriber() -> Transcriber:
    backend = settings().asr_backend.lower()
    if backend == "groq":
        return GroqTranscriber()
    if backend in ("faster-whisper", "local"):
        return LocalTranscriber()
    raise TranscriptionError(f"unknown ASR_BACKEND {backend!r}")


def _brief(text: str, limit: int = 240) -> str:
    text = " ".join((text or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")
