# Cognita — multi-agent research that shows its working

**Live:** https://cognita-web-368646012388.europe-west1.run.app

Ask a research question. A team of agents plans it, searches the web, reads the
sources, checks every claim against them, and writes a cited report with a
confidence score — streaming its progress and the report as it is written.
Upload your own documents and they are searched alongside the web.

> The live demo scales to zero when idle, so the first visit after a quiet spell
> takes 10–20 seconds to wake up. A research run takes about two minutes.

## How it works

```
question ─► triage ─► planner ─► search ─► read ─► corpus ─► analyze ─► fact-check ─► gap analysis ─► report
                                   ▲                                                       │
                                   └──────────── evidence insufficient: search again ──────┘
```

- **LangGraph orchestration.** Nine nodes. Triage decides how much work a
  question needs; gap analysis loops back to search when the evidence is thin.
- **Verification, not just retrieval.** Claims in the draft are checked against
  the sources, and marked when they hold up against one the draft was *not*
  written from. The report carries a confidence score with the reasons behind it.
- **Your documents too.** Uploaded files are chunked, embedded and searched with
  hybrid retrieval (pgvector + Postgres full-text) in the same evidence set.
- **Durable runs.** Research is a job on a Postgres queue, not a request. A
  worker claims it with a fenced lease; progress is stored as events the
  browser replays. A refresh, a dropped connection or a deploy does not lose the
  run — the client reattaches and resumes from the last event it saw.
- **Multi-tenant by construction.** Supabase auth, and Postgres row-level
  security on every table through a low-privilege runtime role, so a missing
  filter in application code returns nothing rather than someone else's data.

## Stack

| | |
|---|---|
| Agents | LangGraph, Groq (gpt-oss-120b / 20b), Tavily search |
| Backend | FastAPI, WebSockets, SQLAlchemy, Alembic |
| Data | Postgres + pgvector (Supabase), fastembed (bge-small) |
| Frontend | React 19, TypeScript, Vite |
| Deploy | Google Cloud Run (API + worker, frontend), Secret Manager |
| Tests | pytest against real Postgres, Vitest; GitHub Actions CI |

## Run it locally

See [research-assistant/SETUP.md](research-assistant/SETUP.md). In short:
Postgres with pgvector, then three processes — the API, the worker, and the
frontend.

```bash
cd research-assistant/backend && uvicorn api.main:app --port 8000
cd research-assistant/backend && python -m worker
cd research-assistant/frontend && npm run dev
```

Deployment notes, costs and known limits: [research-assistant/DEPLOY.md](research-assistant/DEPLOY.md).

## Also in this repository

**[Veracity](veracity/)** — fact-checks video and audio. Transcribes with
timestamps, extracts the factual claims, and checks each against independent
sources.
