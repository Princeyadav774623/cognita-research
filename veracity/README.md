# Veracity

Paste a video or audio file. Get a transcript anchored to timestamps, an
analysis at the depth you asked for, and — at the deepest setting — every
factual claim in it checked against sources the speaker never cited.

A separate product from Cognita in the same repository. It borrows Cognita's
verification idea, because "is this claim actually supported" is the same
problem whether the claim arrived as a web page or as something somebody said
out loud. Everything above that line is new.

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

Each is a superset of the one above and roughly four times the cost, so the
expensive one is opt-in and priced before it runs.

| Mode | Adds | Answers |
|---|---|---|
| `summary` | one pass over the transcript | what was said |
| `deep` | structure, rhetorical moves, extracted claims | what was argued |
| `report` | independent verification, confidence, counter-evidence | whether it holds up |

## What it looks like working

Seventeen seconds of speech with two deliberate falsehoods among six claims:

```
supported     The Eiffel Tower is located in Paris, France.
supported     The Eiffel Tower stands about 330 metres tall.
contradicted  The Eiffel Tower is made entirely of solid gold.
supported     The Eiffel Tower was built in 1889 for the World's Fair.
contradicted  The Eiffel Tower is taller than the Burj Khalifa in Dubai.
supported     Around 7 million people visit the Eiffel Tower every year.

41%  ·  2 claim(s) are contradicted by independent sources.
11,281 tokens  ·  $0.0028
```

Six true claims through the same pipeline score 97%. The number moves for the
right reason.

## Running it

Three processes. Postgres 16 with pgvector, and `ffmpeg` on the PATH.

```bash
cd backend && ./venv/bin/uvicorn app.main:app --port 8080
cd backend && ./venv/bin/python -m app.jobs.worker
cd frontend && npm run dev          # http://localhost:5174
```

See `backend/README.md` for configuration and the things that will bite.

## Layout

```
backend/
  app/
    api/         routes, auth, schemas
    ingest/      probe, audio, transcribe, chunk, resolve
    analysis/    claims, search, verify, perspectives, confidence, pipeline
    jobs/        durable Postgres queue, worker, handlers
    db/          models, session, row-level security
  tests/         57, against real Postgres and real ffmpeg
frontend/        React 19 + Vite
```
