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

## Quotas

Two meters, because the two costs are unrelated. Transcription scales with the
*length* of what you upload; analysis scales with the *depth* you ask for, and a
report is roughly fifteen times a summary. One counter would let someone spend a
month on a single long file, or on forty deep analyses of a thirty-second clip,
and be surprised either way. A cost ceiling sits behind both as a backstop.

| Meter | Free | Pro |
|---|---|---|
| Transcription minutes | 120 | 3,000 |
| Analysis credits | 60 | 1,500 |
| Cost ceiling | $1 | $25 |

Analysis is priced in credits — summary 1, deep 4, report 15 — mirroring the
ratios the interface advertises.

**Every consume is a single UPDATE whose WHERE clause contains the limit.** The
read-compare-write version is not a limit at all: two requests that read at the
same time both see room and both proceed, and that failure appears exactly when
someone is hammering the service. Verified with ten threads racing for one
remaining credit — one succeeded.

The period rolls inside the same statement that charges. Resetting first and
charging second would let a request slip between the two and be charged against
a period that no longer exists.

Consumed on entry, refunded on failure, and only on the *final* attempt —
refunding on every attempt would give allowance back for work about to be
retried. A URL submission is charged a nominal minute up front, since its length
cannot be known until it downloads, and the fetch handler reconciles to the real
duration.

`GET /api/quota` never raises on an exhausted allowance: it is what the interface
calls to decide what to offer, and refusing to report a spent quota would hide
the state the user most needs to see.

## Migrations

```bash
set -a; . ./.env; set +a
./venv/bin/alembic upgrade head
./venv/bin/alembic revision --autogenerate -m "what changed"
```

Startup migrates automatically, so the usual case needs no command.

**The raw-SQL indexes are excluded from autogenerate.** An HNSW index with an
operator class and an expression index over `to_tsvector()` cannot be expressed
in model metadata, so alembic finds them in the database, does not find them in
the models, and proposes dropping them — every single time. `include_object` in
`env.py` filters them out, and `ensure_indexes()` recreates them at startup if
anything removed them anyway. Both guards exist because a dropped index does not
fail: retrieval keeps working, on a sequential scan, and the slowdown gets
attributed to anything but this.

**Autogenerate against an empty database.** Alembic diffs the models against
whatever is connected; run it against a database that already has the tables and
it finds no difference and writes `pass`. The migration looks fine and does
nothing, and nobody notices until a fresh install.

**A database predating Alembic is stamped, not migrated.** Running the initial
migration against existing tables fails on the first CREATE TABLE, and the
obvious workaround — dropping first — destroys the data it was meant to
preserve. Startup detects that case, stamps the baseline, and says so loudly.

Four tests cover this, each against a throwaway database: upgrade builds the
whole schema from nothing, the vector extension is created before the tables
that need it, downgrade removes what upgrade added, and — the one that catches
real drift — the schema the migration builds matches the schema the models
declare, column for column.

## Authentication

Two modes, and the choice is about who issues tokens.

| | |
|---|---|
| `SUPABASE_JWKS_URL` | Supabase signs, we verify against its published keys. This service holds no secret, so leaking its environment cannot mint a token. **Use this in production.** |
| `JWT_SECRET` | A shared HS256 secret, for deployments with no Supabase. The same secret signs and verifies, so anything that can read the environment can issue a token for any user. |
| `ALLOW_GUEST` | Every unauthenticated request becomes one shared identity. Development only — with a single tenant, row-level security separates nothing. Startup warns. |

Algorithms are pinned per mode and never read from the token's own header. A
verifier that trusts `alg` accepts `alg: none`, and accepts an HS256 token
signed with the public RSA key as the shared secret. Both are the verifier's
fault, and both have tests.

Also tested: an expired token, a token signed with the wrong key, a token for
another audience, and a token with no `sub` — the last because a missing subject
would otherwise produce a principal with `user_id=None`, which scopes the
database session to nothing and fails open in the one place it must not.

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

## Asking questions of a transcript

```
POST /api/media/{id}/ask   {"question": "how long does the reef stretch for?"}
```

Chunks are embedded locally at ingest with `bge-small-en-v1.5`, and retrieval is
hybrid — vector search fused with Postgres full-text by Reciprocal Rank Fusion.
Neither half is reliable alone: embeddings put "shut it down" and "start it up"
close together, and keyword search has no notion of paraphrase. RRF fuses by
rank rather than score, because cosine distance and `ts_rank` are different
scales with no meaningful conversion between them.

Local embedding is why measurement is practical: retrieval costs nothing per
query, so it can be evaluated as often as you like. A per-query fee turns
evaluation into something you run once and quote forever.

Two indexes, both added by migration. HNSW on the vector using
`vector_cosine_ops` — an index built for a different operator is silently not
used — and a GIN expression index matching the `to_tsvector()` in the query.
Without them every retrieval is a sequential scan, which looks fine on a
ten-minute clip and falls over on a library.

Declining is a first-class outcome. Asked something the transcript does not
cover, the answer is "the excerpts do not provide information about…" rather
than a fluent paragraph assembled from whatever was topically nearest.

## Analysis

```
POST /api/media/{id}/analysis  {"mode": "summary" | "deep" | "report"}
GET  /api/media/{id}/analysis/{analysis_id}
```

Measured on a 17-second clip at report depth: 6 claims, 11,792 tokens, $0.0032,
about two minutes — most of it the per-claim searches, which run concurrently.

### Verification is independent, or it is circular

The naive design is to extract claims from the transcript and check them against
the transcript. A claim faithfully drawn from what somebody said always agrees
with what they said, including when they were wrong, so that system measures
transcription fidelity and calls the result verification.

Every claim is therefore searched for separately, and the verdict is formed only
from what that search returned. The speaker's own words are context for reading
the evidence, never evidence themselves. The judge is told in as many words not
to use its own knowledge — if the excerpts do not settle it, the answer is
`unsupported` however confident the model feels.

That rule has a visible cost, and it is the right cost. On a test clip, "the
Eiffel Tower was built in 1889 for the World's Fair" came back `unsupported`:
true, but the retrieved sources did not establish it. A system that had answered
`supported` there would have been answering from the model's memory, which is
the thing being guarded against.

Measured on a clip with two deliberate falsehoods among six claims:

```
supported     The Eiffel Tower is located in Paris, France.
supported     The Eiffel Tower stands about 330 meters tall.
contradicted  The Eiffel Tower is made entirely of solid gold.
unsupported   The Eiffel Tower was built in 1889 for the World's Fair.
contradicted  The Eiffel Tower is taller than the Burj Khalifa in Dubai.
supported     Around 7 million people visit the Eiffel Tower every year.

confidence 0.41 — "2 claim(s) are contradicted by independent sources."
```

The same pipeline over six true claims scores 0.97. The number moves for the
right reason.

### Claims are gated on transcription confidence

A claim assembled out of words the transcriber was unsure of is not checked at
all; it is reported as `unclear_audio`. Verifying a misheard number produces
high confidence in something that was never said, which is worse than no verdict
— and it is the failure that would be hardest for a reader to catch.

### Perspectives are searched for, not generated

"Give me other perspectives" asked of a model produces both-sides mush. Instead,
each substantive claim gets a search for material that would *contradict* it,
and what comes back is reported with who holds the position. A claim with no
credible counter-argument returns nothing — manufacturing dissent for a settled
fact is its own dishonesty.

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

## A failed check is not a finding

`unsupported` means the sources were found and did not settle the claim — a
statement about the evidence. When a request fails partway through an analysis,
the verdict is `check_failed` instead, which is a statement about us.

Collapsing the second into the first was the original behaviour and it was
wrong: a rate limit during one claim of six silently reported that claim as
unverified, which reads to a user as "we looked and found nothing". Scoring now
excludes failed checks entirely rather than counting them against the score, and
the factors say how many there were and that re-running will pick them up.


## Diarization: removed rather than faked

`transcript_segments.speaker`, `transcript_chunks.speakers` and `claims.speaker`
existed and were never populated by anything — every value was NULL, while the
schema and the API response both implied the system knew who was talking.

They are gone. Real diarization needs `pyannote.audio`, a gated model download
and a Hugging Face token, which is a substantial dependency to add unverified;
Whisper does not do it and neither does Groq's hosted version. A column that is
always NULL is worse than no column, because it makes a promise the product
cannot keep, and on a debate or an interview — the obvious use case — a reader
would reasonably assume attribution was available.

Adding it properly is worthwhile future work. Implying it is not.
