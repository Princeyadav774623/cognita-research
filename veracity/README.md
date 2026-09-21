# Veracity

Paste a video or audio link, or upload a file. Get back a transcript anchored to
timestamps, an analysis at the depth you asked for, and — at the deepest setting
— every factual claim in it checked against sources the speaker never cited.

It is a separate product from Cognita in the same repository. It borrows
Cognita's verification core, because "is this claim actually supported" is the
same problem whether the claim arrived as a web page or as something somebody
said out loud. Everything above that line is new.

## What it does, and what it deliberately does not

Three different things get called "is this video real", and conflating them is
how products in this space end up lying to their users:

| | Veracity |
|---|---|
| **Factual accuracy** — are the spoken claims true? | Yes. This is the product. |
| **Rhetorical honesty** — misleading while technically true? Missing context? | Yes, via the perspectives pass. |
| **Media authenticity** — is the file itself deepfaked or edited? | **No.** Not attempted, not claimed. |

The third needs forensics and provenance (C2PA), it is largely unsolved, and a
confident answer to it would be a fabrication. The interface says so rather than
leaving the reader to assume.

## The three depths

Each tier is a superset of the one above it, and roughly four times the cost, so
the expensive one is opt-in and priced before it runs.

| Mode | Adds | Answers |
|---|---|---|
| `summary` | one pass over the transcript | what was said |
| `deep` | structure, speakers, extracted claims, topic segmentation | what was argued |
| `report` | independent verification per claim, confidence, counter-evidence | whether it holds up |

## Pipeline

```
url or upload
  -> resolve      yt-dlp for a link, direct for an upload
  -> probe        ffprobe: duration, streams, codec
  -> audio        ffmpeg: 16 kHz mono, segmented under the ASR size limit
  -> transcribe   word-level timestamps AND per-word confidence
  -> chunk        timestamp-anchored, sentence-aligned, overlapping
  -> embed        local, 384-d
  -> analyse      per the requested mode
```

Every downstream artefact keeps its `start_ms`/`end_ms`, so a citation points at
`12:34` in the media rather than at "chunk 7". That is the difference between a
claim a reader can check in three seconds and one they have to take on trust.

## Why ASR confidence is load-bearing

If the transcriber mishears a number, a fact-checker will happily verify a claim
nobody made — and report high confidence in it, because internally everything
agreed. Veracity carries per-word confidence from the ASR all the way into claim
extraction, and a span below the threshold is never fact-checked. It is marked
unclear instead, which is the honest outcome.

## Layout

```
backend/
  app/
    api/         FastAPI routes
    ingest/      resolve, probe, audio, transcribe, chunk, embed
    analysis/    claims, verify, perspectives, confidence
    jobs/        durable Postgres-backed queue and worker
    db/          models, session, row-level security
  migrations/    alembic
  tests/
docs/
```

## Running it

See `backend/README.md`. Postgres 16 with pgvector and `ffmpeg` on the PATH are
the only hard prerequisites; transcription defaults to Groq's hosted Whisper so
there is no model to download.
