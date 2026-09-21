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

## The API

```bash
set -a; . ./.env; set +a
./venv/bin/uvicorn app.main:app --port 8080   # one terminal
./venv/bin/python -m app.jobs.worker          # another
```

| | |
|---|---|
| `POST /api/media` | upload a file, returns `202` with an id |
| `POST /api/media/url` | submit a link — `501` unless `ALLOW_REMOTE_FETCH` |
| `GET /api/media` | your items, newest first |
| `GET /api/media/{id}` | state and metadata |
| `GET /api/media/{id}/transcript` | `409` until the state is `ready` |
| `DELETE /api/media/{id}` | row, segments, chunks and files |
| `GET /health` | database, isolation, configuration |

Upload returns as soon as the row exists. Transcribing an hour takes minutes and
holding the request open for it would exceed every proxy between here and the
browser.

Three things the routes do deliberately:

- **The size cap counts bytes actually written**, not `Content-Length`, which
  the client controls. The body streams to disk a megabyte at a time, so a
  2 GB upload never sits in memory, and a refusal removes both the partial file
  and its row.
- **Another tenant's id returns `404`, not `403`.** A 403 confirms that an id
  exists to somebody who cannot see it.
- **A transcript that is not ready is `409`, not `200` with an empty list.**
  "No transcript yet" and "a transcript with nothing in it" are different
  answers to the same request.

### URL submission is off by default

Fetching from a third-party host generally breaches its terms of service:
defensible for a tool someone runs themselves, a liability for a hosted service.
`ALLOW_REMOTE_FETCH` makes that a deployer's decision.

When it is on, submitted URLs are resolved and checked before yt-dlp sees them.
A URL resolving to a private, loopback or link-local address is refused —
otherwise "paste a link" is a server-side request forgery primitive, and
`http://169.254.169.254/latest/meta-data/` reads cloud credentials.

## The queue

Jobs live in Postgres, not in memory and not in a broker. A worker claims one by
setting a lease into the future; if it dies, the lease expires and the next
worker to poll picks the job up. `FOR UPDATE SKIP LOCKED` is what makes that
safe with several workers running — each locks the row it takes and skips rows
someone else holds, so ten workers polling one table never hand out the same job
twice. There is a test that asserts exactly that with ten threads.

Keeping the queue in the same database as the rows means a media item and the
job that processes it commit together: a job can never reference a row that was
rolled back, and a row can never exist with no job to process it.

```bash
./venv/bin/python -m app.jobs.worker            # all kinds
./venv/bin/python -m app.jobs.worker ingest     # one kind
```

Long stages call `heartbeat()` to push their lease out. Transcribing an hour of
audio outlasts any lease short enough to recover quickly from a crash, and
extending as you go gives both.

## Known limitation: words at a part boundary

Splitting cuts on time, not on speech, so a word straddling a boundary is
clipped — in testing, "outer space" across an 8 s boundary transcribed as
`…from out` / `space.…`. Fixing it properly means overlapping the parts by a
second or two and reconciling the duplicated words at the seam. Until that
exists, parts default to 10 minutes so the damage is one word per ten minutes,
and it is recorded here rather than left to be discovered.
