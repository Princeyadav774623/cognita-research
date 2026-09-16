"""Build the technical appendix: every prompt verbatim, plus reproducible
specifications for the SRS figures.

The prompts are read from the source files rather than retyped, so this
document cannot drift away from what the system actually sends.
"""
import json
import pathlib

ROWS = json.load(open(
    "/private/tmp/claude-501/-Users-princeyadav-Documents-Multi-Agent-AI-Project/"
    "9b5672a2-05e3-4f1e-9c74-d0adac3299cc/scratchpad/prompt-rows.json"))

OUT = pathlib.Path(
    "/Users/princeyadav/Documents/Multi_Agent_AI_Project/research-assistant/docs/"
    "Cognita-Technical-Appendix.html")

# ---------------------------------------------------------------- figures
# Each entry is a complete specification: what the figure must show, the
# elements and relationships it contains, and source a tool can render
# directly. Mermaid because GitHub, Notion and most editors render it inline,
# and because a text source can be diffed when the system changes.
FIGURES = [
 {
  "id": "A.1", "title": "Use Case Diagram",
  "purpose": "The standard SRS view of who does what. Shows that every use case except sign-up passes through authentication, and that quota enforcement sits between the user and the expensive operations.",
  "actors": "Guest (dev only), Registered User, Stripe (external), Groq / Tavily / Supabase (external services)",
  "elements": "11 use cases across two subsystems plus account management. Include-relationships from every research action to <<Authenticate>> and <<Consume quota>>.",
  "layout": "Actors on the left and right edges; use cases in a rounded boundary box labelled 'Cognita'. Group Deep Research cases top, Chat with Files middle, Account bottom.",
  "src": """flowchart LR
  U([Registered User]):::actor
  G([Guest - dev only]):::actor
  S([Stripe]):::actor

  subgraph Cognita
    direction TB
    UC1(Run deep research)
    UC2(Stream live progress)
    UC3(View past reports)
    UC4(Export report)
    UC5(Upload document)
    UC6(Chat with documents)
    UC7(Tune retrieval parameters)
    UC8(Delete document)
    UC9(Sign in / sign up)
    UC10(View quota)
    UC11(Erase all my data)
    AUTH{{Authenticate}}
    QUOTA{{Consume quota}}
  end

  U --> UC1 & UC3 & UC5 & UC6 & UC9 & UC10 & UC11
  G --> UC1 & UC6
  S --> UC10
  UC1 -.->|include| AUTH
  UC1 -.->|include| QUOTA
  UC6 -.->|include| AUTH
  UC1 --> UC2
  UC3 --> UC4
  UC6 --> UC7
  UC5 --> UC8
  classDef actor fill:#fff,stroke:#A06B21,stroke-width:2px;""",
 },
 {
  "id": "A.2", "title": "Context Diagram (DFD Level 0)",
  "purpose": "The system as a single process with its external entities. The point it makes: four external dependencies, and user documents never leave the system boundary.",
  "actors": "User, Supabase (identity), Tavily (search), Groq (inference), Cohere (optional rerank)",
  "elements": "One process 'Cognita', four external entities, one data store. Label every flow with what actually crosses it.",
  "layout": "Process centred; entities arranged around it; data store beneath. Bidirectional arrows labelled on both directions.",
  "src": """flowchart TB
  USER([User])
  SB[/Supabase\\nidentity/]
  TV[/Tavily\\nweb search/]
  GQ[/Groq\\ninference/]
  CH[/Cohere\\nrerank, optional/]
  P((Cognita))
  DB[(PostgreSQL + pgvector)]

  USER -->|question, uploaded file, JWT| P
  P -->|cited report, confidence, telemetry| USER
  P -->|verify JWT via public JWKS| SB
  P -->|sub-queries, claim corroboration| TV
  TV -->|results, snippets, figures| P
  P -->|prompts| GQ
  GQ -->|completions, token usage| P
  P -->|chunks to rerank| CH
  P <-->|sessions, documents, vectors| DB""",
 },
 {
  "id": "A.3", "title": "Data Flow Diagram (Level 1)",
  "purpose": "Decomposes the system into its six real processes and shows which data store each touches. Makes the two-role database access visible.",
  "actors": "—",
  "elements": "Processes 1.0 Authenticate, 2.0 Enforce quota, 3.0 Research pipeline, 4.0 Ingest document, 5.0 Answer from documents, 6.0 Persist session. Stores D1 sessions, D2 documents, D3 chunks+vectors, D4 subscriptions.",
  "layout": "Left-to-right flow; stores along the bottom edge; annotate which database role each process uses.",
  "src": """flowchart LR
  U([User])
  P1[1.0 Authenticate\\nverify JWT]
  P2[2.0 Enforce quota\\nreserve / refund]
  P3[3.0 Research pipeline\\n9-node graph]
  P4[4.0 Ingest document\\nextract, chunk, embed]
  P5[5.0 Answer from documents\\nhybrid retrieve + judge]
  P6[6.0 Persist session\\ntenant-scoped write]

  D1[(D1 research_sessions)]
  D2[(D2 rag_documents)]
  D3[(D3 rag_chunks + vectors)]
  D4[(D4 user_subscriptions)]

  U -->|JWT| P1
  P1 -->|user_id| P2
  P2 <-->|usage| D4
  P2 -->|approved| P3
  P2 -->|approved| P5
  U -->|file| P4
  P4 -->|record| D2
  P4 -->|chunks + embeddings| D3
  P5 <-->|top-k chunks| D3
  P3 -->|corpus evidence| D3
  P3 -->|final state| P6
  P6 -->|row| D1
  P6 -->|report| U
  P5 -->|grounded answer| U""",
 },
 {
  "id": "A.4", "title": "Entity-Relationship Diagram",
  "purpose": "The real schema, including the columns that carry evidence quality. Every table carries or derives a tenant key — that is what makes row-level security expressible.",
  "actors": "—",
  "elements": "Six tables. Note which carry user_id directly and which derive it through a parent, because the RLS policies differ accordingly.",
  "layout": "user_subscriptions and research_sessions on the left; the rag_* cluster on the right. Mark cascade deletes.",
  "src": """erDiagram
  USER_SUBSCRIPTIONS {
    string user_id PK
    string stripe_customer_id
    string plan_tier
    int monthly_queries_used
    datetime usage_period_start
  }
  RESEARCH_SESSIONS {
    string id PK
    string user_id "RLS key"
    string query
    string final_report
    json sources
    json verified_claims
    json images
    float confidence
    int total_tokens
    float estimated_cost_usd
    datetime created_at
  }
  RAG_DOCUMENTS {
    string id PK
    string user_id "RLS key"
    string filename
    string status "processing|ready|error"
    int chunk_count
  }
  RAG_CHUNKS {
    string id PK
    string document_id FK
    int chunk_index
    text content
    vector embedding "384-dim, HNSW"
    tsvector content_tsv "GIN, generated"
  }
  RAG_CONVERSATIONS {
    string id PK
    string user_id "RLS key"
  }
  RAG_MESSAGES {
    string id PK
    string conversation_id FK
    string role
    text content
    text sources
  }
  RAG_DOCUMENTS ||--o{ RAG_CHUNKS : "cascade delete"
  RAG_CONVERSATIONS ||--o{ RAG_MESSAGES : "cascade delete"
  USER_SUBSCRIPTIONS ||--o{ RESEARCH_SESSIONS : "same user_id" """,
 },
 {
  "id": "A.5", "title": "Sequence Diagram — Deep Research run",
  "purpose": "The lifetime of one research request, including the quota refund on failure and the point at which the reflective loop can fire. This is the figure that explains why a run takes minutes.",
  "actors": "Browser, FastAPI, LangGraph, Tavily, Groq, Postgres",
  "elements": "WebSocket handshake with the token in the first message (browsers cannot set headers on a WS handshake), quota reservation before expensive work, streamed progress, persistence, then the completion frame.",
  "layout": "Six lifelines. Use alt/opt blocks for the reflective loop and the refund path.",
  "src": """sequenceDiagram
  participant B as Browser
  participant API as FastAPI
  participant G as LangGraph
  participant T as Tavily
  participant Q as Groq
  participant DB as Postgres

  B->>API: WS connect, then {query, token}
  API->>API: verify JWT (public JWKS)
  API->>DB: consume_quota(user)
  DB-->>API: reserved
  API->>G: stream_research(query, user_id)

  G->>Q: triage - classify effort
  G->>Q: plan - 3-5 sub-queries
  G->>T: search each sub-query
  T-->>G: results + figures
  G->>G: read pages concurrently
  G->>DB: corpus retrieval (tenant-scoped)
  G->>Q: analyse - draft answer
  G->>T: corroborate each claim
  G->>Q: verify claims (batched)
  G->>Q: gap analysis

  alt evidence insufficient and iterations remain
    G->>T: follow-up searches
    G->>Q: re-verify new claims
  end

  G->>Q: write report (streamed)
  G-->>API: token events
  API-->>B: progress + report tokens
  API->>DB: save_session(+ tokens, cost)
  API-->>B: complete

  opt pipeline failed or client disconnected
    API->>DB: refund_quota(user)
  end""",
 },
 {
  "id": "A.6", "title": "Sequence Diagram — Chat with Files query",
  "purpose": "The agentic retrieval loop, which is what produces correct refusals. Shows the grade-rewrite-retry cycle and the independent judge.",
  "actors": "Browser, FastAPI, Retrieval, Postgres, Groq",
  "elements": "Contextualise, hybrid retrieve, grade, conditional rewrite-and-retry, answer, judge. Show the decline branch explicitly.",
  "layout": "Five lifelines; an alt block for the insufficient-evidence path with its two outcomes.",
  "src": """sequenceDiagram
  participant B as Browser
  participant API as FastAPI
  participant R as Retrieval
  participant DB as Postgres
  participant Q as Groq

  B->>API: POST /api/rag/chat {message}
  API->>Q: contextualise against history
  Q-->>API: standalone query
  API->>R: hybrid retrieve
  R->>DB: vector search (HNSW)
  R->>DB: keyword search (GIN tsvector)
  R->>R: reciprocal rank fusion
  R-->>API: top-k chunks

  API->>Q: grade - do these answer it?
  alt insufficient
    API->>Q: rewrite query
    API->>R: retrieve again
    R-->>API: new chunks
    API->>Q: grade again
    alt still insufficient
      API-->>B: decline, no sources
    end
  end

  API->>Q: answer from delimited excerpts
  Q-->>API: grounded answer
  API->>Q: judge - faithfulness + relevance
  Q-->>API: PASS / PARTIAL / FAIL
  API->>DB: persist message + sources
  API-->>B: answer + telemetry""",
 },
 {
  "id": "A.7", "title": "State Diagram — Document lifecycle",
  "purpose": "Explains the status field and the failure mode it exists for. A restart between 'created' and 'embedded' leaves nothing to advance the record, which is why the reaper exists.",
  "actors": "—",
  "elements": "States: Uploaded, Validating, Processing, Ready, Error, Deleted. Transitions labelled with the trigger.",
  "layout": "Vertical flow with Error as a sink reachable from three states.",
  "src": """stateDiagram-v2
  [*] --> Uploaded : POST /api/rag/upload
  Uploaded --> Validating : magic-byte check
  Validating --> Error : wrong signature / too large / empty
  Validating --> Processing : record created, HTTP 200 returned
  Processing --> Ready : extracted, chunked, embedded
  Processing --> Error : no extractable text
  Processing --> Error : stale > 15 min (restart reaper)
  Ready --> Deleted : user deletes
  Error --> Deleted : user deletes
  Ready --> [*]
  Deleted --> [*]""",
 },
 {
  "id": "A.8", "title": "Deployment Diagram",
  "purpose": "Where things run and which database role each path uses — the distinction row-level security depends on.",
  "actors": "—",
  "elements": "Browser node, application node (uvicorn + embedding model in-process), database node, external service nodes. Two labelled connections to the database.",
  "layout": "Stacked nodes; annotate the two DB connections distinctly.",
  "src": """flowchart TB
  subgraph Client
    BR[Browser\\nReact SPA bundle]
  end
  subgraph AppServer[Application server]
    UV[uvicorn / FastAPI]
    EMB[fastembed\\nbge-small-en-v1.5\\nin-process]
    UV --- EMB
  end
  subgraph Data[Database server]
    PG[(PostgreSQL 16\\npgvector + FTS)]
  end
  subgraph External
    GQ[Groq API]
    TV[Tavily API]
    SB[Supabase Auth]
  end

  BR -->|HTTPS + WSS| UV
  UV -->|owner role\\nmigrations + webhooks| PG
  UV -->|cognita_app role\\nRLS applies| PG
  UV --> GQ
  UV --> TV
  UV -->|JWKS fetch| SB""",
 },
 {
  "id": "A.9", "title": "Component Diagram",
  "purpose": "The module structure as it exists on disk, so a reader can map the architecture onto the repository.",
  "actors": "—",
  "elements": "Frontend components, API layer, agent package, RAG package, shared infrastructure. Show the dependency direction.",
  "layout": "Layered, dependencies pointing downward. No upward arrows — that would indicate a cycle.",
  "src": """flowchart TB
  subgraph FE[frontend/src]
    APP[App.tsx - routing]
    MD[Markdown + Chart + AgentGraph]
    RAGUI[RagSection + ChatPanel]
    HOOK[useResearch - WS state]
  end
  subgraph API[backend/api]
    MAIN[main.py - REST + WS]
    RR[rag_routes.py]
    BR[billing_routes.py]
  end
  subgraph AG[backend/agents]
    GRAPH[graph/research_graph.py]
    NODES[9 agent modules]
    EV[evidence.py]
  end
  subgraph RAGP[backend/rag]
    CHAT[chat_agent.py]
    RET[retrieval.py - hybrid]
    ING[ingest.py]
    EMBM[embeddings.py]
  end
  subgraph INF[backend infrastructure]
    DB[db.py + rls.py]
    CONF[confidence.py]
    UTIL[utils.py - retry, tokens]
  end

  APP --> HOOK --> MAIN
  APP --> MD
  RAGUI --> RR
  MAIN --> GRAPH --> NODES --> EV
  NODES --> CONF
  RR --> CHAT --> RET --> EMBM
  RR --> ING
  NODES --> UTIL
  CHAT --> UTIL
  RET --> DB
  GRAPH --> DB
  BR --> DB""",
 },
]

CSS = """
:root{--paper:#f4f1ea;--paper2:#fbf9f5;--card:#fff;--ink:#16150f;--ink2:#474338;--ink3:#7c7566;
--rule:#ddd6c8;--rule2:#eae4d8;--bronze:#a06b21;--teal:#1d5f63;--plum:#6b3352;
--serif:"Newsreader",Georgia,serif;--sans:"Plus Jakarta Sans",-apple-system,sans-serif;
--mono:"JetBrains Mono",Menlo,Consolas,monospace;
--s1:.25rem;--s2:.5rem;--s3:.75rem;--s4:1rem;--s5:1.5rem;--s6:2rem;--s7:3rem;--s8:4rem}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--serif);font-size:16.5px;line-height:1.68;-webkit-font-smoothing:antialiased}
.page{max-width:1020px;margin:0 auto;padding-inline:28px;padding-block:0 var(--s8)}
.measure{max-width:70ch}
.cover{padding-block:var(--s8) var(--s7);border-bottom:3px double var(--ink);margin-bottom:var(--s7)}
.mark{font-family:var(--mono);font-size:.7rem;letter-spacing:.18em;text-transform:uppercase;color:var(--bronze);margin-bottom:var(--s5)}
h1{font-family:var(--sans);font-size:clamp(2.3rem,5.4vw,3.5rem);font-weight:700;letter-spacing:-.038em;line-height:1.04;margin:0 0 var(--s4);text-wrap:balance}
h1 em{font-family:var(--serif);font-style:italic;font-weight:400;color:var(--bronze)}
.sub{font-size:1.15rem;color:var(--ink2);max-width:62ch;margin:0}
h2{font-family:var(--sans);font-size:1.7rem;font-weight:700;letter-spacing:-.026em;margin:var(--s8) 0 var(--s5);padding-bottom:var(--s3);border-bottom:2px solid var(--ink)}
h3{font-family:var(--sans);font-size:1.05rem;font-weight:600;margin:var(--s6) 0 var(--s3)}
p{margin:0 0 var(--s4)}
.toc{background:var(--paper2);border:1px solid var(--rule);border-radius:10px;padding:var(--s5) var(--s6);margin-bottom:var(--s7)}
.toc h4{font-family:var(--sans);font-size:.75rem;letter-spacing:.14em;text-transform:uppercase;color:var(--ink3);margin:0 0 var(--s3)}
.toc ul{list-style:none;margin:0;padding:0;columns:2;column-gap:var(--s7)}
.toc li{margin-bottom:var(--s2);break-inside:avoid}
.toc a{color:var(--ink);text-decoration:none;font-size:.93rem}
.toc a:hover{color:var(--bronze);text-decoration:underline}
.lede{font-size:1.1rem;color:var(--ink2);border-left:3px solid var(--bronze);padding-left:var(--s4);margin-bottom:var(--s5)}
.prompt{background:var(--card);border:1px solid var(--rule);border-radius:10px;margin:var(--s5) 0;overflow:hidden;break-inside:avoid}
.prompt__head{display:flex;flex-wrap:wrap;align-items:baseline;gap:var(--s2) var(--s4);padding:var(--s4) var(--s5);border-bottom:1px solid var(--rule2);background:var(--paper2)}
.prompt__n{font-family:var(--mono);font-size:.7rem;color:var(--bronze);letter-spacing:.1em}
.prompt__role{font-family:var(--sans);font-weight:700;font-size:1.02rem;letter-spacing:-.01em}
.prompt__meta{margin-left:auto;display:flex;gap:var(--s3);flex-wrap:wrap}
.tag{font-family:var(--mono);font-size:.63rem;letter-spacing:.05em;padding:2px 7px;border-radius:3px;background:rgba(29,95,99,.1);color:var(--teal);white-space:nowrap}
.tag--f{background:rgba(160,107,33,.1);color:var(--bronze)}
.prompt__why{padding:var(--s4) var(--s5);font-size:.93rem;color:var(--ink2);border-bottom:1px solid var(--rule2)}
pre{margin:0;padding:var(--s4) var(--s5);background:#fdfcf9;font-family:var(--mono);font-size:.76rem;line-height:1.62;color:var(--ink2);overflow-x:auto;white-space:pre-wrap;word-break:break-word}
.fig{background:var(--card);border:1px solid var(--rule);border-radius:10px;margin:var(--s5) 0;overflow:hidden;break-inside:avoid}
.fig__head{padding:var(--s4) var(--s5);border-bottom:1px solid var(--rule2);background:var(--paper2)}
.fig__id{font-family:var(--mono);font-size:.7rem;color:var(--bronze);letter-spacing:.1em}
.fig__title{font-family:var(--sans);font-weight:700;font-size:1.08rem;margin-top:2px}
.fig__body{padding:var(--s4) var(--s5)}
.spec{display:grid;grid-template-columns:max-content 1fr;gap:var(--s2) var(--s4);font-size:.9rem;margin-bottom:var(--s4)}
.spec dt{font-family:var(--mono);font-size:.64rem;letter-spacing:.09em;text-transform:uppercase;color:var(--ink3);padding-top:4px}
.spec dd{margin:0;color:var(--ink2)}
.note{border-left:3px solid var(--teal);background:rgba(29,95,99,.07);padding:var(--s4) var(--s5);border-radius:0 8px 8px 0;margin:var(--s5) 0;font-size:.95rem}
.note b{font-family:var(--sans)}
code{font-family:var(--mono);font-size:.84em;background:var(--paper2);border:1px solid var(--rule2);border-radius:3px;padding:.08em .32em}
@media(max-width:760px){.toc ul{columns:1}.spec{grid-template-columns:1fr}.page{padding-inline:18px}}
@media print{body{background:#fff;font-size:10pt}h2{break-before:page}.prompt,.fig,.note{break-inside:avoid}pre{font-size:7.6pt}@page{margin:16mm 14mm}}
"""


def build() -> str:
    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cognita — Technical Appendix</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&family=Plus+Jakarta+Sans:wght@400;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>{CSS}</style></head><body><div class="page">

<header class="cover">
  <div class="mark">Technical Appendix · Companion to the Project Report</div>
  <h1>Prompts and <em>figure specifications</em></h1>
  <p class="sub">Every instruction the system sends to a model, reproduced verbatim from source,
  and complete specifications for the SRS figures — each with renderable source so the diagrams
  can be regenerated rather than redrawn.</p>
</header>

<nav class="toc">
  <h4>Contents</h4>
  <ul>
    <li><a href="#partA">Part A — Prompt Catalogue ({len(ROWS)} prompts)</a></li>
    <li><a href="#partB">Part B — Figure Specifications ({len(FIGURES)} figures)</a></li>
    <li><a href="#howto">Part C — Rendering the Figures</a></li>
  </ul>
</nav>

<section id="partA">
<h2>Part A — Prompt Catalogue</h2>
<p class="lede measure">These are extracted from the source files, not retyped, so this document
cannot drift from what the system actually sends. Each entry records the model it goes to, the
temperature it runs at, and why it is worded the way it is.</p>

<div class="note measure"><b>Why temperature varies.</b> Classification and verification run at 0.0
because the same input should give the same verdict — a fact-checker that disagrees with itself
between runs is not a fact-checker. Synthesis runs at 0.2–0.3, low enough to stay close to the
sources and high enough not to produce stilted prose.</div>
"""]

    for i, r in enumerate(ROWS, 1):
        parts.append(f"""
<article class="prompt">
  <div class="prompt__head">
    <span class="prompt__n">A{i:02d}</span>
    <span class="prompt__role">{r['role']}</span>
    <span class="prompt__meta">
      <span class="tag">{r['model']}</span>
      <span class="tag">temp {r['temp']}</span>
      <span class="tag tag--f">{r['file']} · {r['name']}</span>
    </span>
  </div>
  <div class="prompt__why">{r['note']}</div>
  <pre>{r['text']}</pre>
</article>""")

    parts.append("""
</section>

<section id="partB">
<h2>Part B — Figure Specifications</h2>
<p class="lede measure">Nine figures a complete SRS would carry. Each specification states what the
figure must show and why it earns its place, then gives source a tool renders directly — so the
diagram can be regenerated when the system changes rather than redrawn by hand and slowly going
stale.</p>

<div class="note measure"><b>Mermaid rather than an image format.</b> A diagram checked in as text can
be diffed, reviewed and corrected in a pull request. A PNG cannot, which is how architecture
diagrams end up describing a system that no longer exists.</div>
""")

    for f in FIGURES:
        parts.append(f"""
<article class="fig">
  <div class="fig__head">
    <div class="fig__id">Figure {f['id']}</div>
    <div class="fig__title">{f['title']}</div>
  </div>
  <div class="fig__body">
    <dl class="spec">
      <dt>Purpose</dt><dd>{f['purpose']}</dd>
      <dt>Actors</dt><dd>{f['actors']}</dd>
      <dt>Elements</dt><dd>{f['elements']}</dd>
      <dt>Layout</dt><dd>{f['layout']}</dd>
    </dl>
  </div>
  <pre>{f['src']}</pre>
</article>""")

    parts.append("""
</section>

<section id="howto">
<h2>Part C — Rendering the Figures</h2>

<div class="measure">
<h3>In a document</h3>
<p>GitHub, GitLab, Notion and Obsidian render Mermaid from a fenced block labelled
<code>mermaid</code>. Paste the source between the fences and it draws on save — no toolchain.</p>

<h3>As image files</h3>
<p>For Word or LaTeX, render to SVG or PNG with the Mermaid CLI:</p>
<pre>npm install -g @mermaid-js/mermaid-cli
mmdc -i figure-a1.mmd -o figure-a1.svg -b transparent
mmdc -i figure-a1.mmd -o figure-a1.png -s 2   # 2x for print</pre>
<p>Use SVG wherever the target supports it. The project report's own figures were rasterised at 2×
only because no SVG renderer was available on the build machine; at 1× they would be visibly soft
in print.</p>

<h3>Without installing anything</h3>
<p>mermaid.live renders pasted source in the browser and exports SVG or PNG directly. Adequate for
a one-off; the CLI is better once the diagrams are checked in, because it can regenerate all of
them in a single command when the system changes.</p>

<h3>Keeping them honest</h3>
<p>Each specification above names what the figure must show. When the system changes, update the
source and re-render — and if the change contradicts the <em>Purpose</em> line, the figure has
stopped earning its place and should be rethought rather than patched.</p>
</div>
</section>

</div></body></html>""")
    return "".join(parts)


OUT.write_text(build())
print(f"wrote {OUT.name} — {OUT.stat().st_size:,} bytes, "
      f"{len(ROWS)} prompts, {len(FIGURES)} figure specs")
