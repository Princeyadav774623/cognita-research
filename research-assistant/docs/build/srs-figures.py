"""The nine SRS diagrams, hand-drawn as SVG in the report's own palette.

Mermaid's default styling would look like a different document. These use one
visual language throughout, so a reader learns it once:

    bronze  process / system under discussion
    teal    data at rest
    plum    external service
    green   a terminal success state
    red     a terminal failure state
    dashed  an optional or conditional path

Shape carries meaning too: rounded rectangle is a process, cylinder is a store,
slanted parallelogram is something outside the boundary, diamond is a decision.
"""

from xml.sax.saxutils import escape as _esc


def esc(text):
    """Escape label text. Labels legitimately contain angle brackets — the RAG
    prompt wraps excerpts in <document> tags — and pasting those raw produces
    an SVG that silently fails to parse."""
    return _esc(str(text))


BRONZE, TEAL, PLUM = "#a06b21", "#1d5f63", "#6b3352"
GREEN, RED, AMBER = "#1f6b4a", "#9c2f26", "#8a6314"
INK, INK2, INK3, RULE = "#16150f", "#474338", "#7c7566", "#ddd6c8"

DEFS = f"""
<defs>
  <marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
    <path d="M0,0 L10,5 L0,10 z" fill="{INK3}"/></marker>
  <marker id="ab" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
    <path d="M0,0 L10,5 L0,10 z" fill="{BRONZE}"/></marker>
  <marker id="at" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
    <path d="M0,0 L10,5 L0,10 z" fill="{TEAL}"/></marker>
  <marker id="ap" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
    <path d="M0,0 L10,5 L0,10 z" fill="{PLUM}"/></marker>
  <marker id="open" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
    <path d="M0,0 L10,5 L0,10" fill="none" stroke="{INK3}" stroke-width="1.4"/></marker>
</defs>
<style>
  .t  {{ font-family:'Plus Jakarta Sans',sans-serif; font-size:11.5px; fill:{INK}; font-weight:600 }}
  .tc {{ font-family:'Plus Jakarta Sans',sans-serif; font-size:11.5px; fill:{INK}; font-weight:600; text-anchor:middle }}
  .s  {{ font-family:'JetBrains Mono',monospace; font-size:9px; fill:{INK3} }}
  .sc {{ font-family:'JetBrains Mono',monospace; font-size:9px; fill:{INK3}; text-anchor:middle }}
  .lb {{ font-family:'JetBrains Mono',monospace; font-size:8.5px; fill:{INK3} }}
  .lbc{{ font-family:'JetBrains Mono',monospace; font-size:8.5px; fill:{INK3}; text-anchor:middle }}
  .cap{{ font-family:'JetBrains Mono',monospace; font-size:9px; letter-spacing:.1em; text-anchor:middle }}
  .ln {{ stroke:{INK3}; stroke-width:1.3; fill:none; marker-end:url(#a) }}
  .lnb{{ stroke:{BRONZE}; stroke-width:1.4; fill:none; marker-end:url(#ab) }}
  .lnt{{ stroke:{TEAL}; stroke-width:1.4; fill:none; marker-end:url(#at) }}
  .lnp{{ stroke:{PLUM}; stroke-width:1.4; fill:none; marker-end:url(#ap) }}
  .dash{{ stroke-dasharray:4 3 }}
  .proc{{ fill:#fff; stroke:{BRONZE}; stroke-width:1.6 }}
  .store{{ fill:#f7f4ed; stroke:{TEAL}; stroke-width:1.5 }}
  .ext {{ fill:#faf6f8; stroke:{PLUM}; stroke-width:1.5 }}
  .band{{ fill:#faf7f1; stroke:{RULE}; stroke-width:1 }}
  .ok  {{ fill:#eef5f1; stroke:{GREEN}; stroke-width:1.6 }}
  .bad {{ fill:#fbf0ef; stroke:{RED}; stroke-width:1.6 }}
</style>"""


def cyl(x, y, w, h, label, sub=""):
    """Data store drawn as a cylinder."""
    r = 7
    out = (f'<path class="store" d="M{x},{y+r} a{w/2},{r} 0 0,1 {w},0 v{h-2*r} '
           f'a{w/2},{r} 0 0,1 -{w},0 z"/>'
           f'<path d="M{x},{y+r} a{w/2},{r} 0 0,0 {w},0" fill="none" stroke="{TEAL}" stroke-width="1.5"/>')
    out += f'<text class="tc" x="{x+w/2}" y="{y+h/2+2}">{esc(label)}</text>'
    if sub:
        out += f'<text class="sc" x="{x+w/2}" y="{y+h/2+16}">{esc(sub)}</text>'
    return out


def box(x, y, w, h, label, sub="", cls="proc", rx=8):
    out = f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"/>'
    ty = y + h / 2 + (2 if not sub else -3)
    out += f'<text class="tc" x="{x+w/2}" y="{ty}">{esc(label)}</text>'
    if sub:
        out += f'<text class="sc" x="{x+w/2}" y="{ty+14}">{esc(sub)}</text>'
    return out


def para(x, y, w, h, label, sub=""):
    """External entity: slanted parallelogram."""
    k = 12
    out = (f'<path class="ext" d="M{x+k},{y} L{x+w},{y} L{x+w-k},{y+h} L{x},{y+h} z"/>')
    ty = y + h / 2 + (2 if not sub else -3)
    out += f'<text class="tc" x="{x+w/2}" y="{ty}">{esc(label)}</text>'
    if sub:
        out += f'<text class="sc" x="{x+w/2}" y="{ty+14}">{esc(sub)}</text>'
    return out


def actor(x, y, label):
    """Stick figure, the one shape everyone reads as 'a person'."""
    return (f'<g stroke="{BRONZE}" stroke-width="1.6" fill="none">'
            f'<circle cx="{x}" cy="{y}" r="7"/>'
            f'<path d="M{x},{y+7} v16 M{x-10},{y+13} h20 M{x},{y+23} l-8,11 M{x},{y+23} l8,11"/></g>'
            f'<text class="tc" x="{x}" y="{y+48}">{esc(label)}</text>')


def ellipse(cx, cy, rx, ry, label, sub=""):
    out = f'<ellipse class="proc" cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}"/>'
    ty = cy + (3 if not sub else -2)
    out += f'<text class="tc" x="{cx}" y="{ty}">{esc(label)}</text>'
    if sub:
        out += f'<text class="sc" x="{cx}" y="{ty+13}">{esc(sub)}</text>'
    return out


def diamond(cx, cy, w, h, label):
    return (f'<path class="proc" d="M{cx},{cy-h/2} L{cx+w/2},{cy} L{cx},{cy+h/2} L{cx-w/2},{cy} z"/>'
            f'<text class="tc" x="{cx}" y="{cy+3}">{esc(label)}</text>')


def svg(vb_w, vb_h, body):
    # Explicit width/height as well as viewBox: without an intrinsic size a
    # browser rasterising this to a canvas falls back to its own default and
    # produces an image far smaller than the drawing. The stylesheet overrides
    # them to 100% where the figure is inline.
    return (f'<svg viewBox="0 0 {vb_w} {vb_h}" width="{vb_w}" height="{vb_h}" '
            f'xmlns="http://www.w3.org/2000/svg" role="img">'
            f'{DEFS}<rect width="{vb_w}" height="{vb_h}" fill="#ffffff"/>{body}</svg>')


# ----------------------------------------------------------------- A.1
def a1():
    b = ''
    b += actor(76, 86, "Registered user")
    b += actor(76, 258, "Guest (dev)")
    b += actor(790, 172, "Stripe")
    b += f'<rect class="band" x="180" y="30" width="540" height="330" rx="14"/>'
    b += f'<text class="cap" x="450" y="52" fill="{BRONZE}">COGNITA</text>'

    cases = [
        (300, 80, "Run deep research"), (300, 124, "Stream live progress"),
        (300, 168, "View past reports"), (300, 212, "Export report"),
        (600, 80, "Upload document"), (600, 124, "Chat with documents"),
        (600, 168, "Tune retrieval"), (600, 212, "Delete document"),
        (450, 262, "Sign in / sign up"), (450, 300, "View quota"),
        (450, 338, "Erase all my data"),
    ]
    for cx, cy, label in cases:
        b += ellipse(cx, cy, 92, 17, label)

    b += f'<text class="cap" x="300" y="58" fill="{INK3}">DEEP RESEARCH</text>'
    b += f'<text class="cap" x="600" y="58" fill="{INK3}">CHAT WITH FILES</text>'

    for y in (80, 124, 168, 212, 262, 300, 338):
        b += f'<path class="lnb" d="M94,102 C150,102 160,{y} 208,{y}"/>'
    b += f'<path class="lnb" d="M94,272 C150,272 200,124 508,124"/>'
    b += f'<path class="lnb" d="M94,272 C160,272 180,80 208,80"/>'
    b += f'<path class="lnp" d="M772,180 C700,180 640,300 542,300"/>'

    # include-relationships
    # The include-relationship sits below the two columns rather than between
    # them, where it previously overlapped the use cases it points at.
    b += box(352, 236, 196, 34, "«include» authenticate", "then consume quota", rx=17)
    b += f'<path class="ln dash" d="M262,97 C280,170 320,220 {348},250"/>'
    b += f'<path class="ln dash" d="M640,141 C620,190 580,224 {552},248"/>'
    return svg(880, 390, b)


# ----------------------------------------------------------------- A.2
def a2():
    b = ''
    b += ellipse(440, 175, 96, 42, "Cognita", "the system")
    b += actor(84, 150, "User")
    b += para(300, 30, 130, 42, "Supabase", "identity")
    b += para(455, 30, 130, 42, "Tavily", "web search")
    b += para(300, 300, 130, 42, "Groq", "inference")
    b += para(455, 300, 130, 42, "Cohere", "rerank, optional")
    b += cyl(690, 140, 150, 68, "PostgreSQL", "+ pgvector")

    b += f'<path class="lnb" d="M98,168 L338,172"/>'
    b += f'<text class="lb" x="120" y="162">question, file, JWT</text>'
    b += f'<path class="lnb" d="M338,190 L100,196"/>'
    b += f'<text class="lb" x="118" y="212">report, confidence, telemetry</text>'

    b += f'<path class="lnp" d="M400,140 L372,76"/>'
    b += f'<text class="lb" x="200" y="104">verify JWT via public JWKS</text>'
    b += f'<path class="lnp" d="M470,138 L512,76"/>'
    b += f'<text class="lb" x="520" y="104">sub-queries, corroboration</text>'
    b += f'<path class="lnp" d="M404,212 L374,296"/>'
    b += f'<text class="lb" x="196" y="270">prompts / completions</text>'
    b += f'<path class="lnp" d="M472,212 L512,296"/>'
    b += f'<text class="lb" x="520" y="270">chunks to rerank</text>'
    b += f'<path class="lnt" d="M538,175 L686,175"/>'
    b += f'<text class="lb" x="556" y="167">sessions, documents, vectors</text>'
    return svg(880, 360, b)


# ----------------------------------------------------------------- A.3
def a3():
    b = ''
    b += actor(58, 56, "User")
    procs = [
        (130, 40, "1.0 Authenticate", "verify JWT"),
        (300, 40, "2.0 Enforce quota", "reserve / refund"),
        (470, 40, "3.0 Research pipeline", "9-node graph"),
        (470, 140, "5.0 Answer from files", "hybrid + judge"),
        (130, 140, "4.0 Ingest document", "extract, chunk, embed"),
        (660, 40, "6.0 Persist session", "tenant-scoped"),
    ]
    for x, y, t, s in procs:
        b += box(x, y, 150, 56, t, s)

    stores = [(120, 258, "D1 sessions"), (300, 258, "D2 documents"),
              (480, 258, "D3 chunks + vectors"), (660, 258, "D4 subscriptions")]
    for x, y, t in stores:
        b += cyl(x, y, 160, 50, t)

    b += f'<path class="lnb" d="M66,72 L126,68"/><text class="lb" x="62" y="46">JWT</text>'
    b += f'<path class="lnb" d="M280,68 L296,68"/><text class="lb" x="270" y="60">user_id</text>'
    b += f'<path class="lnb" d="M450,68 L466,68"/><text class="lb" x="430" y="60">approved</text>'
    b += f'<path class="lnb" d="M375,96 C400,120 420,140 466,160"/>'
    b += f'<path class="lnb" d="M620,68 L656,68"/>'
    b += f'<path class="lnb" d="M66,88 C90,130 100,150 126,164"/><text class="lb" x="40" y="140">file</text>'

    b += f'<path class="lnt" d="M375,96 L370,254"/><text class="lb" x="378" y="180">usage</text>'
    b += f'<path class="lnt" d="M735,96 L720,254"/>'
    b += f'<path class="lnt" d="M205,196 L215,254"/>'
    b += f'<path class="lnt" d="M545,196 L555,254"/>'
    b += f'<path class="lnt" d="M545,96 C560,150 560,200 560,252"/>'
    b += f'<path class="lnt" d="M700,96 C640,150 300,200 210,254"/>'
    b += f'<text class="lbc" x="450" y="232">every store access is tenant-scoped (RLS)</text>'
    return svg(880, 330, b)


# ----------------------------------------------------------------- A.4
def a4():
    b = ''
    tables = [
        (40, 40, 200, "USER_SUBSCRIPTIONS", ["user_id  PK", "stripe_customer_id", "plan_tier",
                                             "monthly_queries_used", "usage_period_start"], TEAL),
        (40, 230, 200, "RESEARCH_SESSIONS", ["id  PK", "user_id   RLS key", "query",
                                             "final_report", "confidence", "total_tokens",
                                             "estimated_cost_usd"], BRONZE),
        (330, 40, 200, "RAG_DOCUMENTS", ["id  PK", "user_id   RLS key", "filename",
                                         "status", "chunk_count"], BRONZE),
        (330, 230, 200, "RAG_CHUNKS", ["id  PK", "document_id  FK", "chunk_index",
                                       "content", "embedding  vector(384)",
                                       "content_tsv  generated"], TEAL),
        (620, 40, 200, "RAG_CONVERSATIONS", ["id  PK", "user_id   RLS key", "created_at"], BRONZE),
        (620, 170, 200, "RAG_MESSAGES", ["id  PK", "conversation_id  FK", "role",
                                         "content", "sources"], TEAL),
    ]
    for x, y, w, name, cols, colour in tables:
        h = 26 + len(cols) * 15 + 8
        b += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="#fff" stroke="{colour}" stroke-width="1.6"/>'
        b += f'<rect x="{x}" y="{y}" width="{w}" height="24" rx="7" fill="{colour}" opacity="0.1"/>'
        b += f'<text class="t" x="{x+12}" y="{y+16}" style="font-size:10.5px">{name}</text>'
        for i, c in enumerate(cols):
            b += f'<text class="s" x="{x+12}" y="{y+40+i*15}">{c}</text>'

    b += f'<path class="lnt" d="M430,146 L430,226"/>'
    b += f'<text class="lb" x="436" y="190">1 : N cascade</text>'
    b += f'<path class="lnt" d="M720,102 L720,166"/>'
    b += f'<text class="lb" x="726" y="140">1 : N cascade</text>'
    b += f'<path class="ln dash" d="M140,150 L140,226"/>'
    b += f'<text class="lb" x="146" y="192">same user_id</text>'
    b += f'<path class="ln dash" d="M244,70 L326,70"/>'
    b += f'<path class="ln dash" d="M534,70 L616,70"/>'
    b += f'<text class="lbc" x="430" y="382">bronze = carries user_id directly · teal = derives it through a parent</text>'
    return svg(880, 400, b)


# ----------------------------------------------------------------- A.5 / A.6
def sequence(lifelines, steps, width, height, notes=()):
    b = ''
    gap = width / (len(lifelines) + 0.6)
    xs = {}
    for i, (name, kind) in enumerate(lifelines):
        x = gap * (i + 0.8)
        xs[name] = x
        cls = {"p": "proc", "t": "store", "x": "ext"}[kind]
        b += box(x - 52, 18, 104, 34, name, cls=cls, rx=7)
        b += f'<line x1="{x}" y1="52" x2="{x}" y2="{height-20}" stroke="{RULE}" stroke-width="1.2" stroke-dasharray="3 4"/>'
    for frm, to, label, y, style in steps:
        x1, x2 = xs[frm], xs[to]
        cls = {"b": "lnb", "t": "lnt", "p": "lnp", "n": "ln"}[style[0]]
        dash = " dash" if "d" in style else ""
        if frm == to:
            b += f'<path class="{cls}{dash}" d="M{x1},{y} h34 v16 h-34"/>'
            b += f'<text class="lb" x="{x1+40}" y="{y+8}">{esc(label)}</text>'
        else:
            b += f'<path class="{cls}{dash}" d="M{x1},{y} L{x2},{y}"/>'
            mid = (x1 + x2) / 2
            b += f'<text class="lbc" x="{mid}" y="{y-5}">{esc(label)}</text>'
    for x, y, w, h, label in notes:
        b += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="none" stroke="{AMBER}" stroke-width="1.3" stroke-dasharray="5 4"/>'
        b += f'<rect x="{x}" y="{y}" width="52" height="16" rx="4" fill="{AMBER}" opacity="0.15"/>'
        b += f'<text class="lb" x="{x+8}" y="{y+12}" fill="{AMBER}">{esc(label)}</text>'
    return svg(width, height, b)


def a5():
    L = [("Browser", "p"), ("FastAPI", "p"), ("LangGraph", "p"),
         ("Tavily", "x"), ("Groq", "x"), ("Postgres", "t")]
    S = [
        ("Browser", "FastAPI", "WS connect · {query, token}", 78, "b"),
        ("FastAPI", "FastAPI", "verify JWT (JWKS)", 98, "n"),
        ("FastAPI", "Postgres", "consume_quota()", 132, "t"),
        ("FastAPI", "LangGraph", "stream_research()", 154, "b"),
        ("LangGraph", "Groq", "triage · plan", 176, "p"),
        ("LangGraph", "Tavily", "search sub-queries", 198, "p"),
        ("LangGraph", "LangGraph", "read pages", 216, "n"),
        ("LangGraph", "Postgres", "corpus retrieval", 250, "t"),
        ("LangGraph", "Groq", "analyse · draft", 272, "p"),
        ("LangGraph", "Tavily", "corroborate claims", 294, "p"),
        ("LangGraph", "Groq", "verify (batched)", 316, "p"),
        ("LangGraph", "Tavily", "follow-up searches", 356, "pd"),
        ("LangGraph", "Groq", "write report", 400, "p"),
        ("FastAPI", "Browser", "progress + tokens", 422, "b"),
        ("FastAPI", "Postgres", "save_session(+cost)", 444, "t"),
        ("FastAPI", "Postgres", "refund_quota()", 484, "td"),
    ]
    notes = [(330, 338, 500, 34, "alt"), (330, 466, 500, 32, "opt")]
    return sequence(L, S, 880, 520, notes)


def a6():
    L = [("Browser", "p"), ("FastAPI", "p"), ("Retrieval", "p"),
         ("Postgres", "t"), ("Groq", "x")]
    S = [
        ("Browser", "FastAPI", "POST /api/rag/chat", 78, "b"),
        ("FastAPI", "Groq", "contextualise", 100, "p"),
        ("FastAPI", "Retrieval", "hybrid retrieve", 122, "b"),
        ("Retrieval", "Postgres", "vector (HNSW)", 144, "t"),
        ("Retrieval", "Postgres", "keyword (GIN)", 166, "t"),
        ("Retrieval", "Retrieval", "rank fusion", 184, "n"),
        ("FastAPI", "Groq", "grade sufficiency", 220, "p"),
        ("FastAPI", "Groq", "rewrite query", 254, "pd"),
        ("FastAPI", "Retrieval", "retrieve again", 276, "bd"),
        ("Browser", "Browser", "decline", 300, "n"),
        ("FastAPI", "Groq", "answer from <document>", 340, "p"),
        ("FastAPI", "Groq", "judge faithfulness", 362, "p"),
        ("FastAPI", "Postgres", "persist message", 384, "t"),
        ("FastAPI", "Browser", "answer + telemetry", 406, "b"),
    ]
    notes = [(120, 236, 700, 82, "alt")]
    return sequence(L, S, 880, 440, notes)


# ----------------------------------------------------------------- A.7
def a7():
    b = ''
    b += f'<circle cx="60" cy="60" r="9" fill="{INK}"/>'
    b += box(130, 36, 130, 46, "Uploaded", "POST /upload")
    b += box(330, 36, 130, 46, "Validating", "magic bytes")
    b += box(530, 36, 150, 46, "Processing", "extract · embed")
    b += box(530, 170, 150, 46, "Ready", "queryable", cls="ok")
    b += box(330, 170, 130, 46, "Error", "reason stored", cls="bad")
    b += box(530, 280, 150, 46, "Deleted", "cascade")
    b += f'<circle cx="760" cy="303" r="9" fill="none" stroke="{INK}" stroke-width="2"/>'
    b += f'<circle cx="760" cy="303" r="4.5" fill="{INK}"/>'

    b += f'<path class="lnb" d="M72,60 L126,60"/>'
    b += f'<path class="lnb" d="M262,60 L326,60"/>'
    b += f'<path class="lnb" d="M462,60 L526,60"/>'
    b += f'<text class="lbc" x="494" y="52">record created</text>'
    b += f'<text class="lbc" x="494" y="76">HTTP 200 returned</text>'
    b += f'<path class="lnb" d="M605,84 L605,166"/>'
    b += f'<text class="lb" x="612" y="130">embedded</text>'
    b += f'<path class="lnb" d="M395,84 L395,166"/>'
    b += f'<text class="lb" x="288" y="130" fill="{RED}">bad signature</text>'
    b += f'<path class="lnb" d="M526,74 C500,110 470,140 462,168"/>'
    b += f'<text class="lb" x="470" y="112" fill="{RED}">no text</text>'
    b += f'<path class="lnb dash" d="M560,84 C520,120 480,150 462,176"/>'
    b += f'<text class="lb" x="330" y="222" fill="{AMBER}">stale &gt; 15 min — restart reaper</text>'
    b += f'<path class="lnb" d="M605,220 L605,276"/>'
    b += f'<text class="lb" x="612" y="252">user deletes</text>'
    b += f'<path class="lnb" d="M430,216 C440,260 500,296 526,300"/>'
    b += f'<path class="lnb" d="M684,303 L752,303"/>'
    return svg(880, 350, b)


# ----------------------------------------------------------------- A.8
def a8():
    b = ''
    b += f'<rect class="band" x="30" y="28" width="220" height="110" rx="12"/>'
    b += f'<text class="cap" x="140" y="50" fill="{BRONZE}">CLIENT DEVICE</text>'
    b += box(56, 64, 168, 54, "Browser", "React SPA bundle")

    b += f'<rect class="band" x="320" y="28" width="240" height="210" rx="12"/>'
    b += f'<text class="cap" x="440" y="50" fill="{BRONZE}">APPLICATION SERVER</text>'
    b += box(346, 64, 188, 54, "uvicorn / FastAPI", "REST + WebSocket")
    b += box(346, 136, 188, 62, "fastembed", "bge-small-en-v1.5 · in-process")

    b += f'<rect class="band" x="630" y="28" width="220" height="120" rx="12"/>'
    b += f'<text class="cap" x="740" y="50" fill="{TEAL}">DATABASE SERVER</text>'
    b += cyl(660, 66, 160, 66, "PostgreSQL 16", "pgvector · FTS")

    b += f'<rect class="band" x="630" y="176" width="220" height="150" rx="12"/>'
    b += f'<text class="cap" x="740" y="198" fill="{PLUM}">EXTERNAL SERVICES</text>'
    b += para(654, 210, 172, 32, "Groq API")
    b += para(654, 250, 172, 32, "Tavily API")
    b += para(654, 290, 172, 32, "Supabase Auth")

    b += f'<path class="lnb" d="M226,90 L342,90"/>'
    b += f'<text class="lbc" x="284" y="82">HTTPS + WSS</text>'
    b += f'<path class="lnt" d="M538,80 L656,86"/>'
    b += f'<text class="lb" x="546" y="72">owner role — migrations</text>'
    b += f'<path class="lnt" d="M538,104 L656,112"/>'
    b += f'<text class="lb" x="546" y="128">cognita_app role — RLS applies</text>'
    b += f'<path class="lnp" d="M540,170 C580,200 610,222 650,226"/>'
    b += f'<path class="lnp" d="M540,176 C580,220 606,262 650,266"/>'
    b += f'<path class="lnp" d="M540,182 C580,240 604,302 650,306"/>'
    return svg(880, 340, b)


# ----------------------------------------------------------------- A.9
def a9():
    b = ''
    layers = [
        (30, "frontend/src", BRONZE, [
            (60, "App.tsx", "routing + shell"), (250, "Markdown / Chart", "rendering"),
            (440, "RagSection", "upload + chat"), (630, "useResearch", "WebSocket state")]),
        (130, "backend/api", BRONZE, [
            (60, "main.py", "REST + WS"), (250, "rag_routes.py", "documents, chat"),
            (440, "billing_routes.py", "quota, Stripe"), (630, "auth.py", "JWKS verify")]),
        (230, "backend/agents", TEAL, [
            (60, "research_graph", "9-node graph"), (250, "9 agent nodes", "triage → report"),
            (440, "evidence.py", "per-claim selection"), (630, "confidence.py", "scoring + caps")]),
        (330, "backend/rag", TEAL, [
            (60, "chat_agent.py", "agentic loop"), (250, "retrieval.py", "hybrid + RRF"),
            (440, "ingest.py", "extract + chunk"), (630, "embeddings.py", "local vectors")]),
        (430, "infrastructure", PLUM, [
            (60, "db.py", "engines, tenancy"), (250, "rls.py", "policies"),
            (440, "utils.py", "retry, tokens"), (630, "migrations/", "alembic")]),
    ]
    for y, title, colour, mods in layers:
        b += f'<rect class="band" x="30" y="{y}" width="820" height="76" rx="10"/>'
        b += f'<text class="cap" x="60" y="{y+18}" fill="{colour}" style="text-anchor:start">{title.upper()}</text>'
        for x, name, sub in mods:
            b += f'<rect x="{x}" y="{y+26}" width="172" height="38" rx="6" fill="#fff" stroke="{colour}" stroke-width="1.4"/>'
            b += f'<text class="tc" x="{x+86}" y="{y+42}" style="font-size:10.5px">{name}</text>'
            b += f'<text class="sc" x="{x+86}" y="{y+56}">{sub}</text>'
    for y in (106, 206, 306, 406):
        b += f'<path class="lnb" d="M440,{y} L440,{y+24}"/>'
    b += f'<text class="lbc" x="440" y="528">dependencies point downward — no upward arrow, because that would be a cycle</text>'
    return svg(880, 545, b)


FIGURES = [
    ("A.1", "Use Case Diagram", a1,
     "Who does what, and what every research action must pass through first. The include-relationship shows authentication and quota enforcement standing between the user and every expensive operation."),
    ("A.2", "Context Diagram — DFD Level 0", a2,
     "The system as one process with its external entities. Four dependencies, and the user's documents never cross the boundary."),
    ("A.3", "Data Flow Diagram — Level 1", a3,
     "The six real processes and the stores each touches. Every store access is tenant-scoped, which is the property row-level security enforces."),
    ("A.4", "Entity-Relationship Diagram", a4,
     "The schema as deployed. Colour separates tables carrying user_id directly from those deriving it through a parent — the distinction that decides how each RLS policy is written."),
    ("A.5", "Sequence — Deep Research run", a5,
     "One research request end to end. The token travels in the first WebSocket message because browsers cannot set headers on a handshake; quota is reserved before expensive work and refunded if the run fails."),
    ("A.6", "Sequence — Chat with Files query", a6,
     "The agentic retrieval loop. The alt block is what produces correct refusals: grade, rewrite, retry once, and only then decline."),
    ("A.7", "State Diagram — Document lifecycle", a7,
     "Why the status field exists and the failure it guards. A restart between 'record created' and 'embedded' leaves nothing to advance the row, which is what the fifteen-minute reaper is for."),
    ("A.8", "Deployment Diagram", a8,
     "Where each part runs, and the two distinct database connections. That separation is the whole mechanism of row-level security: one role owns the schema, the other cannot bypass the policies."),
    ("A.9", "Component Diagram", a9,
     "The module structure as it exists on disk, layered so dependencies point in one direction only."),
]
