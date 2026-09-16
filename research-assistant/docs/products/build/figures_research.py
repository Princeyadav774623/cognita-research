"""The nine SRS diagrams for Deep Research, drawn for this product alone.

Where the combined report drew Cognita as one system, these draw only the path
a typed question takes through the agent pipeline. Chat with Files appears in
exactly one place — the corpus node — and is drawn there as what it is from
this product's side: an external store the pipeline reads.
"""
from common import (esc, box, cyl, para, actor, ellipse, diamond, svg, arrow,
                    elbow, band, note, lifeline, msg, selfmsg, activation,
                    entity, legend, BRONZE, TEAL, PLUM, GREEN, RED, AMBER,
                    INK, INK2, INK3, RULE)


# ------------------------------------------------------------------ R.1
def r1():
    """Context diagram — the product, its one actor, and every system it talks to."""
    b = actor(72, 196, "Researcher")
    b += band(200, 120, 300, 150, "DEEP RESEARCH")
    b += box(232, 158, 236, 82, "Cognita", "the agent pipeline", rx=10)

    ext = [(600, 40, "Web search API", "sub-query results"),
           (600, 112, "Web pages / PDFs", "full text extraction"),
           (600, 184, "Groq inference", "gpt-oss 20B and 120B"),
           (600, 256, "Supabase auth", "JWT via public JWKS"),
           (600, 328, "Stripe", "subscription state")]
    for x, y, label, sub in ext:
        b += para(x, y, 230, 54, label, sub)

    b += arrow(148, 196, 226, 196, "lnb", "question")
    b += elbow([(148, 214), (176, 214), (176, 300), (200, 300)], "ln", dash=True)
    b += note(176, 320, ["report streamed back", "over one WebSocket"])

    for _, y, _, _ in ext:
        b += arrow(470, 199, 596, y + 27, "lnp")

    b += cyl(232, 292, 236, 56, "Postgres", "sessions, reports, quota")
    b += arrow(350, 240, 350, 290, "lnt")

    b += legend(200, 380, [(BRONZE, "this product"), (PLUM, "outside the boundary"),
                           (TEAL, "data at rest")])
    return svg(880, 410, b)


# ------------------------------------------------------------------ R.2
def r2():
    """DFD level 0 — one process, its stores, and the flows across the boundary."""
    b = para(40, 150, 158, 56, "Researcher", "types a question")
    b += box(300, 140, 260, 92, "1.0  Deep Research", "plan · search · read · verify", rx=12)
    b += para(676, 56, 168, 54, "Web", "search and fetch")
    b += para(676, 168, 168, 54, "Groq", "inference")

    b += arrow(200, 168, 296, 168, "lnb", "question", ly=160)
    b += elbow([(296, 214), (250, 214), (250, 250), (119, 250), (119, 210)],
               "ln", dash=True)
    b += note(140, 268, ["cited report + confidence breakdown"])

    b += elbow([(562, 162), (620, 162), (620, 84), (672, 84)], "lnp")
    b += note(600, 120, ["sub-queries"])
    b += arrow(562, 196, 672, 196, "lnp")
    b += note(592, 188, ["prompts"])

    b += cyl(300, 320, 150, 54, "D1  sessions", "runs and reports")
    b += cyl(490, 320, 150, 54, "D2  user corpus", "another product's store")
    b += arrow(375, 234, 375, 316, "lnt")
    b += arrow(565, 318, 565, 236, "lnt")
    b += note(596, 268, ["read only — the corpus node",
                         "borrows what Chat with Files stored"])

    b += legend(40, 402, [(BRONZE, "process"), (TEAL, "data store"),
                          (PLUM, "external entity"), (INK3, "dashed = conditional")])
    return svg(880, 430, b)


# ------------------------------------------------------------------ R.3
def r3():
    """DFD level 1 — the nine nodes as numbered processes."""
    b = para(24, 60, 124, 50, "Researcher", "")
    b += para(24, 270, 124, 50, "Web", "search + pages")

    left = [(48, "1.1 Triage", "classify effort · 20B"),
            (124, "1.2 Planner", "3-5 sub-queries · 20B"),
            (200, "1.3 Search", "dedupe by URL"),
            (276, "1.4 Reader", "HTML + PDF")]
    right = [(48, "1.5 Corpus", "user documents"),
             (124, "1.6 Analyst", "synthesise · 120B"),
             (200, "1.7 Fact-checker", "verify · 120B"),
             (276, "1.8 Gap analysis", "loop or report? · 20B")]
    for y, label, sub in left:
        b += box(190, y, 170, 58, label, sub)
    for y, label, sub in right:
        b += box(420, y, 170, 58, label, sub)
    b += box(650, 170, 170, 58, "1.9 Report", "assemble · 120B")

    for i in range(3):
        b += arrow(275, left[i][0] + 58, 275, left[i + 1][0], "lnb")
        b += arrow(505, right[i][0] + 58, 505, right[i + 1][0], "lnb")

    b += arrow(148, 78, 186, 72, "lnb")
    b += elbow([(360, 305), (392, 305), (392, 77), (416, 77)], "lnb")

    b += cyl(650, 48, 170, 52, "D2 user corpus", "")
    b += arrow(646, 74, 598, 76, "lnt")
    b += note(650, 116, ["owned by Chat with Files;", "this product only reads it"])

    b += elbow([(590, 305), (618, 305), (618, 199), (646, 199)], "lnb")
    b += note(624, 262, ["sufficient"], BRONZE)

    b += cyl(650, 320, 170, 52, "D1 sessions", "")
    b += arrow(735, 228, 735, 316, "lnt")

    b += elbow([(505, 334), (505, 362), (160, 362), (160, 229), (186, 229)],
               "lnb", dash=True, label="insufficient - re-search", lx=330, ly=378)

    b += arrow(148, 295, 186, 303, "lnp")
    b += elbow([(148, 282), (172, 282), (172, 215), (186, 215)], "lnp")

    # Routed outside the D2 cylinder (x 650-820, y 48-100) rather than up
    # through the middle of it.
    b += elbow([(820, 199), (842, 199), (842, 20), (86, 20), (86, 56)], "ln", dash=True)
    b += note(330, 14, ["cited report, streamed back to the browser"])

    b += legend(24, 404, [(BRONZE, "pipeline node"), (TEAL, "store"),
                          (PLUM, "external entity"), (INK3, "dashed = conditional")])
    return svg(880, 432, b)


# ------------------------------------------------------------------ R.4
def r4():
    """Use case diagram — what a user can do with this product."""
    b = actor(76, 130, "Researcher")
    b += actor(76, 300, "Guest (dev)")
    b += actor(800, 200, "Stripe")
    b += band(190, 26, 540, 356, "DEEP RESEARCH")

    cases = [(460, 76, "Ask a research question", ""),
             (460, 124, "Watch the pipeline run live", ""),
             (460, 172, "Read the confidence breakdown", ""),
             (460, 220, "Inspect and open every source", ""),
             (460, 268, "Re-open a past report", ""),
             (460, 316, "Export Markdown / BibTeX / PDF", ""),
             (460, 358, "Consume monthly quota", "")]
    for cx, cy, label, sub in cases:
        b += ellipse(cx, cy, 158, 18, label)

    for cy in (76, 124, 172, 220, 268, 316):
        b += arrow(112, 140, 300, cy, "ln")
    b += arrow(112, 306, 302, 316, "ln")
    b += elbow([(792, 208), (700, 208), (700, 358), (620, 358)], "lnp")

    b += note(200, 402, ["Uploading a document is NOT a use case of this product — that belongs to",
                         "Chat with Files. The corpus node reads what that product already stored."])
    return svg(880, 434, b)


# ------------------------------------------------------------------ R.5
def r5():
    """Sequence diagram — one complete run, question to report."""
    TOP, BOT = 26, 530
    X = {"br": 86, "ws": 248, "pl": 430, "ex": 612, "pg": 782}
    b = ""
    b += lifeline(X["br"], TOP, BOT, "Browser")
    b += lifeline(X["ws"], TOP, BOT, "WebSocket")
    b += lifeline(X["pl"], TOP, BOT, "LangGraph pipeline")
    b += lifeline(X["ex"], TOP, BOT, "Web + Groq", "ext")
    b += lifeline(X["pg"], TOP, BOT, "Postgres", "store")
    b += note(X["ws"] - 44, 82, ["/ws/research"])

    rows = [
        ("br", "ws", "open socket, send question", "ln", False),
        ("ws", "pg", "consume 1 query from quota", "lnt", False),
        ("ws", "pl", "invoke graph", "lnb", False),
        ("pl", "ex", "triage, then plan sub-queries  (20B)", "lnp", False),
        ("pl", "ex", "run searches, fetch and extract pages", "lnp", False),
        ("pl", "pg", "retrieve from the user's corpus", "lnt", True),
        ("pl", "ex", "synthesise a draft  (120B)", "lnp", False),
        ("pl", "ex", "verify every claim independently  (120B)", "lnp", False),
    ]
    y = 118
    for a, c, label, cls, dash in rows:
        x1, x2 = X[a], X[c]
        b += msg(x1 + (6 if x2 > x1 else -6), x2 + (-6 if x2 > x1 else 6), y, label, cls, dash)
        y += 32

    b += selfmsg(X["pl"] + 6, y, "gap analysis: is the evidence enough?")
    y += 52
    b += elbow([(X["pl"] - 6, y - 14), (348, y - 14), (348, 214), (X["pl"] - 8, 214)],
               "lnb", dash=True)
    b += note(258, 300, ["no - loop back", "to searching"], BRONZE)

    y += 16
    for a, c, label, cls in [("pl", "pg", "persist report, tokens and cost", "lnt"),
                             ("pl", "ws", "stream report tokens", "lnb"),
                             ("ws", "br", "render progressively", "ln")]:
        x1, x2 = X[a], X[c]
        b += msg(x1 + (6 if x2 > x1 else -6), x2 + (-6 if x2 > x1 else 6), y, label, cls)
        y += 32

    b += note(24, 556, ["Responses are omitted for clarity. Every step also emits a progress event on the",
                        "same socket — that stream is what drives the live pipeline animation in the interface."])
    return svg(880, 590, b)


# ------------------------------------------------------------------ R.6
def r6():
    """Entity-relationship diagram — what a research run persists.

    Column names are the real ones, read from backend/db.py. There is no users
    table: identity is delegated to Supabase, so user_id is a subject claim from
    a verified JWT and there is nothing local to join to.
    """
    b = para(40, 52, 190, 52, "Supabase identity", "user_id comes from a JWT")

    e1, h1 = entity(300, 44, 250, "research_sessions",
                    ["id", "user_id", "query", "status", "final_report",
                     "sources  (JSON)", "images  (JSON)", "verified_claims  (JSON)",
                     "confidence", "total_tokens", "estimated_cost_usd",
                     "error", "created_at"], pk="id")
    e2, h2 = entity(620, 44, 230, "user_subscriptions",
                    ["user_id", "stripe_customer_id", "stripe_subscription_id",
                     "plan_tier", "status", "monthly_queries_used",
                     "usage_period_start"], pk="user_id")
    b += e1 + e2

    b += elbow([(230, 78), (265, 78), (265, 80), (296, 80)], "lnt")
    b += note(238, 98, ["1 : N"], TEAL)
    # Routed over the top rather than straight across: at any y between the two
    # boxes this line would pass through research_sessions.
    b += elbow([(230, 66), (265, 66), (265, 22), (735, 22), (735, 40)], "lnt")
    b += note(486, 16, ["1 : 1"], TEAL)

    b += note(40, 150,
              ["No local users table.",
               "user_id is the Supabase",
               "subject claim, verified",
               "against a public JWKS",
               "endpoint. Nothing in this",
               "database owns identity."])

    b += note(300, 44 + h1 + 30,
              ["sources, images and verified_claims are JSON columns on the session row rather than",
               "tables of their own. They are written once when the run finishes and are never queried",
               "across runs, so normalising them would buy joins nobody performs.",
               "",
               "Both tables carry a row-level security policy keyed on app.current_user_id, and",
               "current_setting(..., true) returns NULL when it is unset — so a connection with no",
               "tenant set matches zero rows rather than every row."])
    b += legend(300, 424, [(TEAL, "entity and relationship"), (BRONZE, "key column"),
                           (PLUM, "outside the boundary")])
    return svg(880, 452, b)


# ------------------------------------------------------------------ R.7
def r7():
    """State transition diagram — the lifecycle of one research run."""
    b = f'<circle cx="70" cy="60" r="9" fill="{INK}"/>'
    states = [(140, 36, "triaging", ""), (140, 124, "planning", ""),
              (140, 212, "searching", ""), (140, 300, "reading", ""),
              (410, 36, "retrieving corpus", ""), (410, 124, "analysing", ""),
              (410, 212, "verifying", ""), (410, 300, "gap check", "")]
    for x, y, label, sub in states:
        b += box(x, y, 190, 52, label, sub)

    b += arrow(79, 60, 136, 60, "lnb")
    for i in range(3):
        b += arrow(235, 36 + 52 + i * 88, 235, 124 + i * 88, "lnb")
    b += elbow([(330, 326), (366, 326), (366, 62), (406, 62)], "lnb")
    for i in range(3):
        b += arrow(505, 36 + 52 + i * 88, 505, 124 + i * 88, "lnb")

    b += box(680, 36, 170, 52, "reporting", "", cls="proc")
    b += box(680, 168, 170, 52, "complete", "", cls="ok")
    b += box(680, 268, 170, 52, "declined", "low confidence", cls="ok")
    b += box(680, 368, 170, 52, "failed", "provider or network", cls="bad")

    b += elbow([(600, 310), (640, 310), (640, 62), (676, 62)], "lnb")
    b += note(596, 176, ["evidence", "sufficient"], BRONZE)
    b += arrow(765, 88, 765, 164, "lnt")
    b += elbow([(600, 326), (626, 326), (626, 294), (676, 294)], "lnb", dash=True,
               label="ceiling reached", lx=652, ly=350)
    # Turns down at x=350, clear of the reading box (x 140-330) whose bottom edge
    # this line used to run along for thirty pixels.
    b += elbow([(410, 352), (350, 352), (350, 394), (676, 394)], "lnb", dash=True)
    b += note(392, 386, ["any state, on unrecoverable provider failure"], RED)

    b += elbow([(410, 326), (378, 326), (378, 440), (235, 440), (235, 352)],
               "lnb", dash=True, label="insufficient and iterations remain", lx=306, ly=458)

    b += note(40, 96, ["quota is consumed on", "entry and refunded", "if the run fails"], INK3)
    b += legend(40, 480, [(BRONZE, "in progress"), (GREEN, "terminal success"),
                          (RED, "terminal failure"), (INK3, "dashed = conditional")])
    return svg(880, 506, b)


# ------------------------------------------------------------------ R.8
def r8():
    """Deployment diagram — where this product's work physically runs."""
    b = band(30, 30, 240, 190, "CLIENT")
    b += box(56, 66, 188, 54, "Browser", "React 19 SPA")
    b += box(56, 138, 188, 54, "WebSocket client", "streams progress")

    b += band(310, 30, 270, 300, "APPLICATION NODE")
    b += box(336, 66, 218, 54, "uvicorn / FastAPI", "async workers")
    b += box(336, 138, 218, 54, "LangGraph runtime", "nine nodes, in-process")
    b += box(336, 210, 218, 54, "token ledger", "per-run usage and cost")
    b += note(336, 284, ["the pipeline is in-process:", "no queue, no worker fleet"])

    b += band(620, 30, 230, 120, "DATA NODE")
    b += cyl(646, 66, 178, 62, "PostgreSQL 16", "sessions + quota")

    b += band(620, 186, 230, 240, "EXTERNAL")
    b += para(646, 218, 178, 48, "Groq", "20B / 120B")
    b += para(646, 278, 178, 48, "Web search", "sub-queries")
    b += para(646, 338, 178, 48, "Supabase", "JWKS")

    b += arrow(248, 92, 332, 92, "ln", "HTTPS")
    b += arrow(248, 164, 332, 100, "lnb", "WSS")
    b += arrow(558, 96, 642, 96, "lnt", "cognita_app role")
    b += arrow(558, 164, 642, 240, "lnp")
    b += arrow(558, 172, 642, 300, "lnp")
    b += note(30, 362, ["all runtime queries use the low-privilege role, so row-level",
                        "security applies to every read this product makes"])
    return svg(880, 452, b)


# ------------------------------------------------------------------ R.9
def r9():
    """Activity diagram — the reflective loop, which is the whole point."""
    b = f'<circle cx="150" cy="40" r="9" fill="{INK}"/>'
    b += arrow(150, 49, 150, 72, "lnb")
    b += box(60, 72, 180, 46, "Classify effort", "triage")
    b += arrow(150, 118, 150, 146, "lnb")
    b += diamond(150, 176, 150, 60, "research needed?")

    b += elbow([(225, 176), (320, 176), (320, 210), (426, 210)], "lnb")
    b += note(268, 168, ["no"], BRONZE)
    b += box(430, 186, 180, 48, "Answer directly", "chat reply", cls="ok")
    b += arrow(610, 210, 636, 210, "lnb")

    b += arrow(150, 206, 150, 238, "lnb")
    b += note(158, 228, ["yes"], BRONZE)
    b += box(60, 238, 180, 46, "Plan sub-queries")
    b += arrow(150, 284, 150, 312, "lnb")
    b += box(60, 312, 180, 46, "Search and read")
    b += arrow(150, 358, 150, 386, "lnb")
    b += box(60, 386, 180, 46, "Retrieve user corpus")
    b += arrow(150, 432, 150, 460, "lnb")
    b += box(60, 460, 180, 46, "Synthesise draft")
    b += arrow(240, 483, 344, 483, "lnb")
    b += box(350, 460, 200, 46, "Verify each claim")
    b += note(350, 528, ["searched separately and concurrently, against",
                         "sources the draft was not written from"])
    b += arrow(450, 460, 450, 420, "lnb")
    b += diamond(450, 386, 190, 62, "evidence sufficient?")

    b += elbow([(355, 386), (300, 386), (300, 335), (244, 335)], "lnb", dash=True)
    b += note(256, 322, ["no - iterations remain"], BRONZE)
    b += arrow(545, 386, 634, 386, "lnb")
    b += note(570, 378, ["yes"], BRONZE)
    b += box(640, 362, 190, 48, "Score the run")
    b += arrow(735, 362, 735, 326, "lnb")
    b += box(640, 278, 190, 48, "Assemble report", "sources joined in code")
    b += arrow(735, 278, 735, 238, "lnt")
    b += box(640, 186, 190, 48, "Stream to browser", "", cls="ok")
    b += arrow(735, 186, 735, 164, "lnb")
    b += f'<circle cx="735" cy="150" r="11" fill="none" stroke="{INK}" stroke-width="2"/>'
    b += f'<circle cx="735" cy="150" r="6" fill="{INK}"/>'

    b += note(60, 568, ["The backward edge is the structural claim of this product: a chain cannot return to an",
                        "earlier step, a graph with conditional edges can, and thin evidence is exactly the case",
                        "where returning is the correct behaviour."])
    return svg(880, 612, b)


FIGURES = [
    ("R.1", "Context diagram", r1,
     "Deep Research and everything outside it. One human actor, five external systems, one store of its own."),
    ("R.2", "Data flow diagram — level 0", r2,
     "The product as a single process. The dashed read of the user corpus is the only flow it shares with the other product."),
    ("R.3", "Data flow diagram — level 1", r3,
     "The nine nodes as numbered processes. The dashed return path from gap analysis to search is the reflective loop."),
    ("R.4", "Use case diagram", r4,
     "Everything a user can do with this product. Uploading is deliberately absent — that belongs to Chat with Files."),
    ("R.5", "Sequence diagram — one research run", r5,
     "A full run from a typed question to a streamed report, including the loop back to search."),
    ("R.6", "Entity-relationship diagram", r6,
     "What a run persists. Sources and claims live inside the session payload rather than in tables of their own."),
    ("R.7", "State transition diagram", r7,
     "The lifecycle of a single run, with its three terminal states and the conditional edge that re-enters searching."),
    ("R.8", "Deployment diagram", r8,
     "Where the work runs. The pipeline is in-process on the application node — no queue and no worker fleet."),
    ("R.9", "Activity diagram", r9,
     "The reflective loop drawn as control flow, with the two decisions that shape every run."),
]
