# Veracity — backend

## Prerequisites

- **PostgreSQL 16** with `pgvector`
- **ffmpeg** on the PATH (`brew install ffmpeg`) — used to decode media to PCM
- **yt-dlp**, only if `ALLOW_REMOTE_FETCH=true`

Transcription defaults to Groq's hosted Whisper, so there is no model to
download and no GPU required. Set `ASR_BACKEND=faster-whisper` for a deployment
where audio must not leave the machine.

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env     # fill in GROQ_API_KEY and the two database URLs
./venv/bin/python -m pytest tests -q
```

## The ingestion chain

```python
info   = probe(src)                                   # refuse non-media early
wav    = extract(src, dest)                           # 16 kHz mono PCM
parts  = segment(wav, out, seconds=600, max_bytes=...)# under the upload cap
tr     = transcribe_parts(parts)                      # timed, confidence-carrying
chunks = chunk_transcript(tr.segments)                # retrieval units, still timed
```

Each stage is independently testable and none of them need the database.

## Three things that are not obvious

**Splitting does not use ffmpeg.** It was the obvious tool and it was wrong
twice. The `segment` muxer leaves a sub-second remnant and writes the *source's*
total sample count into every part's header, so probing part four of a
thirty-second file reports thirty seconds. Cutting explicitly with `-ss`/`-t`
replaced that with something worse: on ffmpeg 9.0.2 certain offsets produce no
packets at all — 13.9 s and 14.1 s cut cleanly, 14.0 s fails outright. ffmpeg now
decodes once to a single WAV and the split is byte arithmetic over PCM frames,
where a second is exactly 32,000 bytes and every offset is exact by
construction.

**Language is reported as a name and accepted as a code.** Whisper returns
`"English"` and its API takes `"en"`. Forwarding what part one detected into
part two fails the entire job — and only ever for multi-part media, which is to
say only for the long files that matter. `language_code()` is the seam.

**ASR confidence is derived, and says so.** Whisper emits a per-segment average
log-probability, not a per-word probability. Groq returns no per-word figure at
all, so every `Word.measured` is `False` there and `True` under faster-whisper.
The distinction reaches the database because a fact-checker that verifies a
misheard number will report high confidence in a claim nobody made.

## Known limitation: words at a part boundary

Splitting cuts on time, not on speech, so a word straddling a boundary is
clipped — in testing, "outer space" across an 8 s boundary transcribed as
`…from out` / `space.…`. Fixing it properly means overlapping the parts by a
second or two and reconciling the duplicated words at the seam. Until that
exists, parts default to 10 minutes so the damage is one word per ten minutes,
and it is recorded here rather than left to be discovered.
