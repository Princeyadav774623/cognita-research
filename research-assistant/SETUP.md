# Setup Guide — Get Running in 10 Minutes

## Step 1: Clone / Create Project

```bash
# Create folder
mkdir research-assistant && cd research-assistant
```

## Step 2: Set Up Python Environment

```bash
cd backend
python -m venv venv

# Windows:
venv\Scripts\activate

# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

## Step 3: Get Your Free API Keys

| Service | URL | Time |
|---|---|---|
| Groq | https://console.groq.com | 2 min |
| Tavily | https://tavily.com | 2 min |
| Cohere | https://cohere.com | 2 min |
| LangSmith | https://smith.langchain.com | 2 min |

## Step 4: Configure .env

```bash
cp .env.example .env
# Open .env and paste your API keys
```

## Step 5: Test Everything Works

```bash
# From project root
cd backend
python ../run.py
```

You should see a research report printed in your terminal.
If you do, everything is working!

## Step 6: Start the API Server

```bash
cd backend
uvicorn api.main:app --reload --port 8000
```

API is now live at: http://localhost:8000
Docs at: http://localhost:8000/docs   ← Test all endpoints here

## Step 7: Test the API

```bash
curl -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What is artificial intelligence?"}'
```

## Step 8: Run Tests

```bash
cd backend
pytest tests/ -v
```

## Common Errors

**`GROQ_API_KEY not found`** → Make sure .env file exists and has the key

**`ModuleNotFoundError`** → Run `pip install -r requirements.txt` again

**`Connection timeout`** → Check your internet connection

**`Rate limit exceeded`** → Groq free tier: wait 1 minute and retry

---

## Project File Structure

```
research-assistant/
├── backend/
│   ├── agents/
│   │   ├── search_agent.py      ← Searches web with Tavily
│   │   ├── reader_agent.py      ← Reads URLs and PDFs
│   │   ├── analyst_agent.py     ← Synthesizes with DeepSeek R1
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
