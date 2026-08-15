# Multi-Agent AI Research Assistant — Complete Project Roadmap
### Industry-Standard | Production-Ready | 2025-2026 Stack

---

## Project Overview

Build a system where multiple specialized AI agents collaborate to answer complex research questions:
- **Search Agent** — finds relevant sources from the web
- **Reader Agent** — extracts and parses PDF/document content
- **Analyst Agent** — synthesizes findings across sources
- **Fact-Check Agent** — verifies claims and flags contradictions
- **Report Agent** — generates structured, cited final answers

**End result:** A deployed web app where a user types a research question and gets a cited, verified, multi-source answer in minutes.

---

## Tech Stack (Industry Standard 2026)

| Layer | Technology | Why |
|---|---|---|
| Language | Python 3.12+ | Industry default for AI |
| Agent Framework | LangGraph 0.2+ | Production multi-agent orchestration (beats LangChain for complex flows) |
| LLM APIs | OpenAI GPT-4o + Anthropic Claude 3.5 | Dual-model resilience |
| Vector DB | PostgreSQL + pgvector | Production-grade, no extra infra |
| Web Search | Tavily API | Built for LLM agents, structured results |
| PDF Parsing | PyMuPDF + Unstructured.io | Best accuracy for messy PDFs |
| Backend | FastAPI + Uvicorn | Async, fast, industry standard |
| Frontend | React 18 + TypeScript + Tailwind CSS | Modern, typed, clean |
| State Management | Zustand | Lightweight, perfect for chat apps |
| Real-time | WebSockets (FastAPI native) | Live agent status streaming |
| Database | PostgreSQL (Supabase) | Free tier, production-ready |
| Cache | Redis (Upstash) | Session state, rate limiting |
| Auth | Clerk or Supabase Auth | Auth without the headache |
| Containerization | Docker + Docker Compose | Run anywhere |
| CI/CD | GitHub Actions | Industry standard pipeline |
| Deployment | Railway (backend) + Vercel (frontend) | Free tiers, easy setup |
| Monitoring | LangSmith | Trace every agent call, debug visually |

---

## Week-by-Week Roadmap

---

### WEEK 1 — Foundation & Environment Setup

**Goal:** Dev environment ready, APIs connected, first agent running

**Tasks:**
1. Set up project structure (monorepo: `/backend`, `/frontend`)
2. Create virtual environment, install core packages
3. Set up `.env` with API keys (OpenAI, Anthropic, Tavily, LangSmith)
4. Configure LangSmith tracing (so every agent call is logged from day 1)
5. Build your first simple LangGraph node — a single "Search Agent" that takes a query and returns Tavily results
6. Write unit tests for the search agent

**Packages to install:**
```bash
pip install langgraph langchain-openai langchain-anthropic tavily-python \
            fastapi uvicorn pymupdf unstructured psycopg2-binary \
            redis python-dotenv pytest
```

**Project structure:**
```
research-assistant/
├── backend/
│   ├── agents/
│   │   ├── search_agent.py
│   │   ├── reader_agent.py
│   │   ├── analyst_agent.py
│   │   ├── factcheck_agent.py
│   │   └── report_agent.py
│   ├── graph/
│   │   └── research_graph.py      # LangGraph orchestration
│   ├── api/
│   │   └── main.py                # FastAPI app
│   ├── db/
│   │   └── database.py            # PostgreSQL connection
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   └── App.tsx
├── docker-compose.yml
├── .github/workflows/ci.yml
└── README.md
```

**Week 1 deliverable:** Single agent that searches a query and prints structured results.

---

### WEEK 2 — Build All 5 Agents

**Goal:** Each agent works independently before connecting them

**Search Agent (search_agent.py)**
- Input: research query string
- Tool: Tavily search API
- Output: list of `{url, title, snippet, relevance_score}`
- Handle: rate limiting, duplicate URLs, failed requests

**Reader Agent (reader_agent.py)**
- Input: URL or PDF file path
- Tools: `requests` + `BeautifulSoup` for web, `PyMuPDF` for PDFs
- Output: cleaned text chunks with metadata
- Handle: paywalls, broken links, encoding issues

**Analyst Agent (analyst_agent.py)**
- Input: list of text chunks from Reader
- Uses: pgvector to embed and store chunks, semantic search to find relevant parts
- Output: synthesized answer with source references
- Model: GPT-4o (best reasoning)

**Fact-Check Agent (factcheck_agent.py)**
- Input: draft answer from Analyst
- Behavior: re-queries sources, flags unverified claims, adds confidence scores
- Output: verified answer + list of flagged claims

**Report Agent (report_agent.py)**
- Input: verified answer + all source metadata
- Output: formatted markdown report with citations, summary, and key takeaways

**Week 2 deliverable:** Each agent runs and outputs correctly when called individually.

---

### WEEK 3 — LangGraph Orchestration

**Goal:** Connect all agents into a stateful workflow graph

**Key concepts to implement:**

```python
# research_graph.py - simplified structure
from langgraph.graph import StateGraph, END
from typing import TypedDict, List

class ResearchState(TypedDict):
    query: str
    search_results: List[dict]
    extracted_content: List[str]
    draft_answer: str
    verified_answer: str
    final_report: str
    current_step: str

# Build the graph
graph = StateGraph(ResearchState)
graph.add_node("search", search_agent)
graph.add_node("read", reader_agent)
graph.add_node("analyze", analyst_agent)
graph.add_node("factcheck", factcheck_agent)
graph.add_node("report", report_agent)

# Connect nodes
graph.add_edge("search", "read")
graph.add_edge("read", "analyze")
graph.add_edge("analyze", "factcheck")
graph.add_edge("factcheck", "report")
graph.add_edge("report", END)
```

**Advanced: Add conditional routing**
- If search returns < 3 results → retry with reformulated query
- If fact-check confidence < 0.6 → loop back to search with refined terms
- If PDF fails to parse → fall back to web scraping

**Week 3 deliverable:** Full pipeline runs end-to-end from terminal. One query in → full report out.

---

### WEEK 4 — FastAPI Backend + WebSockets

**Goal:** Expose the agent pipeline as a real API with live streaming

**Endpoints to build:**
```
POST /api/research          → Start a research session, return session_id
GET  /api/research/{id}     → Get results for a session
WS   /ws/research/{id}      → Real-time agent status stream
GET  /api/history           → Past research sessions (from DB)
DELETE /api/research/{id}   → Delete a session
```

**WebSocket streaming (the impressive part):**
Stream each agent's status live so the frontend can show:
- "🔍 Searching web for sources..."
- "📄 Reading 4 documents..."
- "🧠 Analyzing and synthesizing..."
- "✅ Fact-checking claims..."
- "📝 Generating final report..."

```python
# main.py
@app.websocket("/ws/research/{session_id}")
async def research_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    async for event in run_research_graph(session_id):
        await websocket.send_json({
            "step": event["step"],
            "status": event["status"],
            "data": event.get("data")
        })
```

**Database schema (PostgreSQL):**
```sql
CREATE TABLE research_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT,
    query TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    result JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE source_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES research_sessions(id),
    url TEXT,
    title TEXT,
    content_embedding vector(1536),  -- pgvector
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Week 4 deliverable:** Postman/curl can hit the API and get a streamed response.

---

### WEEK 5 — React Frontend

**Goal:** Clean, professional UI that streams live agent updates

**Pages to build:**
1. **Home** — Query input box, example questions, recent searches
2. **Research** — Live agent status, streaming output, progress indicator
3. **Report** — Full rendered report with citations, copy/export buttons
4. **History** — Past sessions, searchable

**Key components:**
```
/components
├── QueryInput.tsx          — Search bar with submit
├── AgentStatusStream.tsx   — Live WebSocket status panel
├── ReportRenderer.tsx      — Markdown → styled HTML
├── SourceCard.tsx          — Individual source with preview
├── ConfidenceScore.tsx     — Visual trust meter for claims
└── ExportButton.tsx        — Download as PDF/MD
```

**UI libraries:**
- `shadcn/ui` — Beautiful, accessible components
- `react-markdown` — Render the agent's markdown output
- `framer-motion` — Smooth agent status animations
- `zustand` — Global state (session, results)

**Week 5 deliverable:** Full working web app locally. You can type a question, watch agents work in real-time, and read the final report.

---

### WEEK 6 — Docker, CI/CD & Deployment

**Goal:** Deployed, publicly accessible, resume-worthy

**Docker setup:**
```yaml
# docker-compose.yml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on: [db, redis]
  
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
  
  db:
    image: pgvector/pgvector:pg16
    volumes: [postgres_data:/var/lib/postgresql/data]
  
  redis:
    image: redis:7-alpine
```

**GitHub Actions CI pipeline (.github/workflows/ci.yml):**
```yaml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: pytest backend/tests/ -v
      - name: Type check
        run: mypy backend/
      - name: Lint
        run: ruff check backend/
```

**Deployment:**
- Backend → Railway (connect GitHub, auto-deploys on push)
- Frontend → Vercel (same, zero config)
- Database → Supabase (PostgreSQL + pgvector, free tier)
- Redis → Upstash (free tier)

**Week 6 deliverable:** Live URL you can share with anyone. GitHub repo with green CI badge.

---

### WEEK 7 — Polish, README & Portfolio Prep

**Goal:** Make it look like a senior engineer built it

**README must include:**
- Live demo GIF (record with OBS or Loom, convert to GIF)
- Architecture diagram (use Excalidraw or draw.io)
- Clear setup instructions (someone else should be able to run it in 5 minutes)
- Tech stack badges
- Screenshots of the UI

**Code quality checklist:**
- [ ] Type hints on all Python functions
- [ ] Error handling for all API calls
- [ ] Rate limiting on your API endpoints
- [ ] Input validation with Pydantic
- [ ] Logging (use Python `logging`, not print statements)
- [ ] Environment variables for all secrets (never hardcoded)
- [ ] At least 70% test coverage

**Bonus features that impress recruiters:**
- Upload your own PDF to research against
- Compare two competing answers on same topic
- Export report as PDF
- Add user auth (Clerk free tier)
- Cost tracker (show $ spent per research session)

---

## Resources (Free, Up-to-Date)

| Topic | Resource |
|---|---|
| LangGraph | [LangGraph Docs](https://langchain-ai.github.io/langgraph/) + LangChain Academy (free course) |
| FastAPI | [FastAPI official tutorial](https://fastapi.tiangolo.com/tutorial/) |
| pgvector | [Supabase Vector guide](https://supabase.com/docs/guides/ai/vector-columns) |
| React + TypeScript | [React TypeScript Cheatsheet](https://react-typescript-cheatsheet.netlify.app/) |
| shadcn/ui | [shadcn.com/docs](https://ui.shadcn.com/) |
| Docker | [Docker Getting Started](https://docs.docker.com/get-started/) |
| GitHub Actions | [GitHub Actions Quickstart](https://docs.github.com/en/actions/quickstart) |
| LangSmith | [LangSmith Docs](https://docs.smith.langchain.com/) |

---

## Budget Estimate (Running This Project)

| Service | Cost |
|---|---|
| OpenAI API | ~$5–10 for development |
| Anthropic API | ~$5 for development |
| Tavily API | Free tier (1000 searches/month) |
| Supabase | Free tier |
| Railway | Free tier ($5 credit) |
| Vercel | Free tier |
| Upstash Redis | Free tier |
| **Total** | **~$10–15 to build and deploy** |

---

## What This Project Proves to a Recruiter

- You understand **agentic AI systems** (the current frontier)
- You can build **production APIs** with FastAPI and WebSockets
- You know **vector databases** and semantic search
- You can **deploy and maintain** a full-stack system
- You write **testable, typed, clean code**
- You've used **LangSmith for observability** (most juniors don't even know this exists)

This is not a tutorial project. This is something you designed and built. That difference is everything.

---

*Roadmap version: 2026 | Stack last validated: July 2026*
