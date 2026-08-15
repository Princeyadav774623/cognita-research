# Setup Guide — Get Running in 10 Minutes

All paths below are relative to the `research-assistant/` project root.

## Step 1: Set Up Python Environment

Requires Python 3.11 or 3.12.

```bash
cd backend
python -m venv venv

# Windows:
venv\Scripts\activate

# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

## Step 2: Get Your Free API Keys

| Service | URL | Time | Required? |
|---|---|---|---|
| Groq | https://console.groq.com | 2 min | Yes |
| Tavily | https://tavily.com | 2 min | Yes |
| Supabase | https://supabase.com | 5 min | Yes — Postgres + auth |
| Cohere | https://cohere.com | 2 min | Optional — reranking |
| LangSmith | https://smith.langchain.com | 2 min | Optional — tracing |

## Step 3: Configure .env

The template lives at the project root; the backend reads `backend/.env`:

```bash
# From the research-assistant/ project root
cp .env.example backend/.env
# Open backend/.env and paste your API keys
```

`DATABASE_URL` and `APP_DATABASE_URL` are both required — the app is
Postgres-only (pgvector is needed for RAG, and SQLite is explicitly rejected
at startup). `APP_DATABASE_URL` should point at a low-privilege role without
BYPASSRLS so Row-Level Security applies to runtime queries.

For the frontend:

```bash
cp frontend/.env.example frontend/.env
# Fill in VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
```

## Step 4: Test Everything Works

```bash
cd backend
python ../run.py
```

You should see a research report printed in your terminal.
If you do, everything is working!

## Step 5: Start the API Server

```bash
cd backend
uvicorn api.main:app --reload --port 8000
```

API is now live at: http://localhost:8000
Docs at: http://localhost:8000/docs   ← Test all endpoints here

## Step 6: Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

Requires Node 20.19+ or 22.12+. The app runs at http://localhost:5173.

## Step 7: Test the API

Every `/api/*` route requires a Supabase JWT, so an unauthenticated curl gets
a 401. Grab a token by signing in through the frontend and copying
`access_token` from the Supabase session in your browser's dev tools:

```bash
curl -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  -d '{"query": "What is artificial intelligence?"}'
```

## Step 8: Run Tests

```bash
cd backend
pytest -v
```

## Running with Docker

```bash
# From the research-assistant/ project root
docker compose up --build
```

Compose reads backend secrets from `backend/.env`. The frontend's `VITE_*`
values are baked in at *build* time, so `VITE_SUPABASE_URL` and
`VITE_SUPABASE_ANON_KEY` must be exported in your shell (or placed in a root
`.env`) before running the build. Leave `VITE_API_URL` unset so the browser
calls the frontend's own origin and nginx proxies through to the backend.

## Common Errors

**`GROQ_API_KEY not found`** → Make sure `backend/.env` exists and has the key

**`ModuleNotFoundError`** → Run `pip install -r requirements.txt` again

**`DATABASE_URL is required`** → The app is Postgres-only; set both
`DATABASE_URL` and `APP_DATABASE_URL` in `backend/.env`

**`SUPABASE_URL is required`** → Auth needs the project URL to fetch its
public JWKS; set `SUPABASE_URL` in `backend/.env`

**`Connection timeout`** → Check your internet connection

**`Rate limit exceeded`** → Groq free tier: wait 1 minute and retry

**`402 Monthly quota exceeded`** → Free tier allows 10 research queries per
calendar month; the counter resets at the start of the next month

---

## Project File Structure

```
research-assistant/
├── backend/
│   ├── agents/
│   │   ├── search_agent.py      ← Searches web with Tavily
│   │   ├── reader_agent.py      ← Reads URLs and PDFs
│   │   ├── analyst_agent.py     ← Synthesizes with Llama 3.3 70B
│   │   ├── factcheck_agent.py   ← Verifies claims
│   │   └── report_agent.py      ← Generates final report
│   ├── graph/
│   │   ├── state.py             ← Shared state TypedDict
│   │   └── research_graph.py    ← LangGraph orchestration
│   ├── api/
│   │   └── main.py              ← FastAPI server + WebSocket
│   ├── tests/
│   │   └── test_agents.py       ← Unit tests
│   ├── config.py                ← Settings / env vars
│   └── requirements.txt
├── run.py                       ← Quick test script
└── .env.example                 ← Copy to .env
```
